//! Own the SQLite connection and its acquired lock as one ordered lifetime.
use super::*;
use std::ops::Deref;

pub(super) struct StoreConnection {
    connection: Option<Connection>,
    owner: Option<File>,
    shutdown_hold: bool,
    #[cfg(test)]
    fail_unlock: bool,
}

impl StoreConnection {
    pub(super) fn acquire(directory: &Path, create: bool) -> Result<Self> {
        let path = directory.join("owner.lock");
        if !create {
            private_file(&path)?;
        }
        let owner = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(create)
            .mode(0o600)
            .open(path)?;
        // Only an acquired lock may ever be explicitly unlocked by this owner.
        owner
            .try_lock()
            .map_err(|e| Error::source_error(Code::Busy, "store owner lock", e))?;
        Ok(Self {
            connection: None,
            owner: Some(owner),
            shutdown_hold: false,
            #[cfg(test)]
            fail_unlock: false,
        })
    }

    pub(super) fn open_database(&mut self, path: &Path) -> Result<()> {
        assert!(self.connection.is_none());
        self.connection = Some(Connection::open_with_flags(
            path,
            OpenFlags::SQLITE_OPEN_READ_WRITE,
        )?);
        Ok(())
    }

    fn finish(&mut self) -> Result<()> {
        if self.shutdown_hold && self.connection.is_some() {
            return Err(Error::new(Code::Busy, "store owner shutdown unconfirmed"));
        }
        if let Some(connection) = self.connection.take()
            && let Err((connection, error)) = connection.close()
        {
            self.connection = Some(connection);
            return Err(Error::source_error(
                Code::StoreUnavailable,
                "close SQLite connection",
                error,
            ));
        }
        if let Some(owner) = self.owner.take() {
            #[cfg(test)]
            if self.fail_unlock {
                return Err(Error::source_error(
                    Code::StoreUnavailable,
                    "release store owner lock",
                    std::io::Error::from_raw_os_error(5),
                ));
            }
            owner.unlock().map_err(|error| {
                Error::source_error(Code::StoreUnavailable, "release store owner lock", error)
            })?;
        }
        Ok(())
    }

    pub(super) fn hold_shutdown(&mut self, hold: bool) {
        self.shutdown_hold = hold;
    }

    // An unconfirmed shutdown or failed SQLite close must not hand ownership over. Keep both
    // resources until process exit; never silently retry or unlock a live connection.
    fn retain_failed_close(&mut self) {
        if let Some(connection) = self.connection.take() {
            std::mem::forget(connection);
            if let Some(owner) = self.owner.take() {
                std::mem::forget(owner);
            }
        }
    }

    pub(super) fn close(mut self) -> Result<()> {
        let result = self.finish();
        if result.is_err() {
            self.retain_failed_close();
        }
        result
    }

    #[cfg(test)]
    pub(super) fn duplicate_owner(&self) -> std::io::Result<File> {
        self.owner.as_ref().expect("live owner").try_clone()
    }
}

impl Deref for StoreConnection {
    type Target = Connection;

    fn deref(&self) -> &Connection {
        self.connection.as_ref().expect("opened Store connection")
    }
}

impl Drop for StoreConnection {
    fn drop(&mut self) {
        if let Err(error) = self.finish() {
            self.retain_failed_close();
            // Drop cannot return an error. Explicit Store::close / Service::stop
            // retain the original source; fallback diagnostics contain no data.
            eprintln!("RadishLink Store shutdown failed: {error}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        service::Service,
        store::tests::{Workspace, clock},
    };

    #[test]
    fn owner_shutdown_hold_prevents_connection_close_and_unlock_until_confirmed() {
        let w = Workspace::new();
        let mut store = w.create();
        store.begin_owner_shutdown();
        let err = store.conn.finish().unwrap_err();
        assert_eq!(err.operation, "store owner shutdown unconfirmed");
        assert!(store.conn.connection.is_some());
        assert_eq!(
            Store::open(&w.dir, Limits::default(), clock(0))
                .err()
                .unwrap()
                .code,
            Code::Busy
        );
        store.finish_owner_shutdown(Ok(())).unwrap();
        store.close().unwrap();
        w.reopen(0).close().unwrap();
    }
    use std::error::Error as _;

    #[test]
    fn explicit_close_preserves_exclusivity_and_releases_surviving_duplicate() {
        let w = Workspace::new();
        let store = w.create();
        let inherited = store.conn.duplicate_owner().unwrap();
        for _ in 0..2 {
            assert_eq!(
                Store::open(&w.dir, Limits::default(), clock(1))
                    .err()
                    .unwrap()
                    .code,
                Code::Busy
            );
        }
        store.close().unwrap();
        let reopened = w.reopen(1);
        drop(inherited);
        assert_eq!(
            Store::open(&w.dir, Limits::default(), clock(1))
                .err()
                .unwrap()
                .code,
            Code::Busy
        );
        reopened.close().unwrap();
        w.reopen(1).close().unwrap();
    }

    #[test]
    fn initialization_error_releases_only_its_acquired_owner() {
        let w = Workspace::new();
        fs::DirBuilder::new().mode(0o700).create(&w.dir).unwrap();
        let mut inherited = None;
        let result = (|| -> Result<()> {
            let mut connection = StoreConnection::acquire(&w.dir, true)?;
            inherited = Some(connection.duplicate_owner().unwrap());
            connection.open_database(&w.dir.join("missing.sqlite3"))?;
            Ok(())
        })();
        assert!(result.is_err());
        let replacement = StoreConnection::acquire(&w.dir, false).unwrap();
        assert_eq!(
            StoreConnection::acquire(&w.dir, false).err().unwrap().code,
            Code::Busy
        );
        drop(inherited);
        assert_eq!(
            StoreConnection::acquire(&w.dir, false).err().unwrap().code,
            Code::Busy
        );
        replacement.close().unwrap();
    }

    #[test]
    fn unwinding_releases_connection_before_unlocking_owner() {
        let w = Workspace::new();
        let store = w.create();
        let inherited = store.conn.duplicate_owner().unwrap();
        let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(move || {
            let _store = store;
            panic!("controlled owner unwind");
        }));
        assert!(panic.is_err());
        let reopened = w.reopen(1);
        drop(inherited);
        assert_eq!(
            Store::open(&w.dir, Limits::default(), clock(1))
                .err()
                .unwrap()
                .code,
            Code::Busy
        );
        reopened.close().unwrap();
    }

    #[test]
    fn failed_sqlite_close_keeps_owner_and_original_error_until_process_exit() {
        let w = Workspace::new();
        let store = w.create();
        // A safe, bounded synthetic unfinished statement forces SQLite close to fail.
        // This one test intentionally retains the connection/lock until the test process exits.
        let statement = store.conn.prepare("SELECT 1").unwrap();
        std::mem::forget(statement);
        let error = store.close().unwrap_err();
        assert_eq!(error.code, Code::StoreUnavailable);
        assert_eq!(error.operation, "close SQLite connection");
        assert!(
            matches!(error.source().unwrap().downcast_ref::<rusqlite::Error>(), Some(rusqlite::Error::SqliteFailure(code, _)) if code.code == rusqlite::ErrorCode::DatabaseBusy)
        );
        assert_eq!(
            Store::open(&w.dir, Limits::default(), clock(1))
                .err()
                .unwrap()
                .code,
            Code::Busy
        );
    }

    #[test]
    fn service_stop_reports_unlock_failure_instead_of_success() {
        let w = Workspace::new();
        let mut store = w.create();
        store.conn.fail_unlock = true;
        let service = Service::start(store).unwrap();
        let error = service.stop().unwrap_err();
        assert_eq!(error.code, Code::StoreUnavailable);
        assert_eq!(error.operation, "release store owner lock");
        assert_eq!(
            error
                .source()
                .unwrap()
                .downcast_ref::<std::io::Error>()
                .unwrap()
                .raw_os_error(),
            Some(5)
        );
    }

    #[test]
    fn service_stop_releases_owner_despite_surviving_duplicate() {
        let w = Workspace::new();
        let store = w.create();
        let inherited = store.conn.duplicate_owner().unwrap();
        let service = Service::start(store).unwrap();
        assert_eq!(
            Store::open(&w.dir, Limits::default(), clock(1))
                .err()
                .unwrap()
                .code,
            Code::Busy
        );
        service.stop().unwrap();
        let reopened = w.reopen(1);
        drop(inherited);
        assert_eq!(
            Store::open(&w.dir, Limits::default(), clock(1))
                .err()
                .unwrap()
                .code,
            Code::Busy
        );
        reopened.close().unwrap();
    }
}
