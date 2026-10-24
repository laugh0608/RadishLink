use radishlink_node::{
    config::Config,
    error::{Code, Error, Result},
};
use std::{env, fs::File, process::ExitCode};

fn run() -> Result<()> {
    let args: Vec<_> = env::args_os().skip(1).collect();
    if args.len() == 2 && args[0] == "check-config" {
        Config::read(File::open(&args[1])?)?;
        println!("configuration valid; service readiness: SECURITY_UNAVAILABLE");
        return Ok(());
    }
    if args.len() == 1 && args[0] == "run" {
        return Err(Error::new(
            Code::SecurityUnavailable,
            "platform unlock and security integration required",
        ));
    }
    Err(Error::new(
        Code::InvalidInput,
        "usage: radishlink-node check-config PATH | run",
    ))
}
fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("{e}");
            ExitCode::from(2)
        }
    }
}
