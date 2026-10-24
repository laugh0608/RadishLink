# Node 第一批第三方依赖记录

更新日期：2026-10-24。直接依赖为 rusqlite 0.40.2（bundled）、serde 1.0.229（derive）、serde_json 1.0.151；Cargo 1.97.1 完全离线解析了已有本地缓存，未安装或更新全局依赖。缓存来源不是新的来源认证结论。

本图独立于密码 spike：SQLite native 为 libsqlite3-sys 0.38.2 / SQLite 3.53.2，不修改 mls-rs 的旧 lock/provider。未来联合安全事务接入需要解决不同 native SQLite 版本的整图兼容，不能强制复制旧锁或静默升级候选。

下表记录 Cargo metadata 与实际存在的许可证文件，已核对文件非空。许可正文摘要用于追溯；不是独立法律意见、完整安全审计或公开分发义务已关闭的结论。完整图版本/归档校验和以 Cargo.lock 为准。

| 包 / 版本 | 声明许可证 | 许可文件与 SHA-256 |
| --- | --- | --- |
| [bitflags 2.13.2](https://crates.io/crates/bitflags/2.13.2) | MIT OR Apache-2.0 | LICENSE-APACHE: `a60eea817514531668d7e00765731449fe14d059d3249e0bc93b36de45f759f2`; LICENSE-MIT: `6485b8ed310d3f0340bf1ad1f47645069ce4069dcc6bb46c7d5c6faf41de1fdb` |
| [cc 1.9.0](https://crates.io/crates/cc/1.9.0) | MIT OR Apache-2.0 | LICENSE-APACHE: `a60eea817514531668d7e00765731449fe14d059d3249e0bc93b36de45f759f2`; LICENSE-MIT: `378f5840b258e2779c39418f3f2d7b2ba96f1c7917dd6be0713f88305dbda397` |
| [fallible-iterator 0.3.0](https://crates.io/crates/fallible-iterator/0.3.0) | MIT/Apache-2.0 | LICENSE-APACHE: `c6596eb7be8581c18be736c846fb9173b69eccf6ef94c5135893ec56bd92ba08`; LICENSE-MIT: `0816e154b159ba255c563f7c8c7df5bbb8cc5fc96f5ab8cf9f4743b4f41fe7eb` |
| [fallible-streaming-iterator 0.1.9](https://crates.io/crates/fallible-streaming-iterator/0.1.9) | MIT/Apache-2.0 | LICENSE-APACHE: `c6596eb7be8581c18be736c846fb9173b69eccf6ef94c5135893ec56bd92ba08`; LICENSE-MIT: `8dcec5569a9be5b0e086c80faed6f1aefa670af0ec29cecc2f714303096887e0` |
| [find-msvc-tools 0.1.15](https://crates.io/crates/find-msvc-tools/0.1.15) | MIT OR Apache-2.0 | LICENSE-APACHE: `a60eea817514531668d7e00765731449fe14d059d3249e0bc93b36de45f759f2`; LICENSE-MIT: `378f5840b258e2779c39418f3f2d7b2ba96f1c7917dd6be0713f88305dbda397` |
| [itoa 1.0.18](https://crates.io/crates/itoa/1.0.18) | MIT OR Apache-2.0 | LICENSE-APACHE: `62c7a1e35f56406896d7aa7ca52d0cc0d272ac022b5d2796e7d6905db8a3636a`; LICENSE-MIT: `23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3` |
| [libsqlite3-sys 0.38.2](https://crates.io/crates/libsqlite3-sys/0.38.2) | MIT | LICENSE: `c10c1f27337546471e5f7e4e97fdd398b35b9d4e126115dcd22de8d8e65abf6f` |
| [memchr 2.8.3](https://crates.io/crates/memchr/2.8.3) | Unlicense OR MIT | COPYING: `01c266bced4a434da0051174d6bee16a4c82cf634e2679b6155d40d75012390f`; LICENSE-MIT: `0f96a83840e146e43c0ec96a22ec1f392e0680e6c1226e6f3ba87e0740af850f`; UNLICENSE: `7e12e5df4bae12cb21581ba157ced20e1986a0508dd10d0e8a4ab9a4cf94e85c` |
| [pkg-config 0.3.34](https://crates.io/crates/pkg-config/0.3.34) | MIT OR Apache-2.0 | LICENSE-APACHE: `a60eea817514531668d7e00765731449fe14d059d3249e0bc93b36de45f759f2`; LICENSE-MIT: `378f5840b258e2779c39418f3f2d7b2ba96f1c7917dd6be0713f88305dbda397` |
| [proc-macro2 1.0.107](https://crates.io/crates/proc-macro2/1.0.107) | MIT OR Apache-2.0 | LICENSE-APACHE: `62c7a1e35f56406896d7aa7ca52d0cc0d272ac022b5d2796e7d6905db8a3636a`; LICENSE-MIT: `23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3` |
| [quote 1.0.47](https://crates.io/crates/quote/1.0.47) | MIT OR Apache-2.0 | LICENSE-APACHE: `62c7a1e35f56406896d7aa7ca52d0cc0d272ac022b5d2796e7d6905db8a3636a`; LICENSE-MIT: `23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3` |
| [rusqlite 0.40.2](https://crates.io/crates/rusqlite/0.40.2) | MIT | LICENSE: `c10c1f27337546471e5f7e4e97fdd398b35b9d4e126115dcd22de8d8e65abf6f` |
| [serde 1.0.229](https://crates.io/crates/serde/1.0.229) | MIT OR Apache-2.0 | LICENSE-APACHE: `62c7a1e35f56406896d7aa7ca52d0cc0d272ac022b5d2796e7d6905db8a3636a`; LICENSE-MIT: `23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3` |
| [serde_core 1.0.229](https://crates.io/crates/serde_core/1.0.229) | MIT OR Apache-2.0 | LICENSE-APACHE: `62c7a1e35f56406896d7aa7ca52d0cc0d272ac022b5d2796e7d6905db8a3636a`; LICENSE-MIT: `23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3` |
| [serde_derive 1.0.229](https://crates.io/crates/serde_derive/1.0.229) | MIT OR Apache-2.0 | LICENSE-APACHE: `62c7a1e35f56406896d7aa7ca52d0cc0d272ac022b5d2796e7d6905db8a3636a`; LICENSE-MIT: `23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3` |
| [serde_json 1.0.151](https://crates.io/crates/serde_json/1.0.151) | MIT OR Apache-2.0 | LICENSE-APACHE: `62c7a1e35f56406896d7aa7ca52d0cc0d272ac022b5d2796e7d6905db8a3636a`; LICENSE-MIT: `23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3` |
| [shlex 2.0.1](https://crates.io/crates/shlex/2.0.1) | MIT OR Apache-2.0 | LICENSE-APACHE: `553fffcd9b1cb158bc3e9edc35da85ca5c3b3d7d2e61c883ebcfa8a65814b583`; LICENSE-MIT: `4455bf75a91154108304cb283e0fea9948c14f13e20d60887cf2552449dea3b1` |
| [smallvec 1.16.3](https://crates.io/crates/smallvec/1.16.3) | MIT OR Apache-2.0 | LICENSE-APACHE: `a60eea817514531668d7e00765731449fe14d059d3249e0bc93b36de45f759f2`; LICENSE-MIT: `0b28172679e0009b655da42797c03fd163a3379d5cfa67ba1f1655e974a2a1a9` |
| [syn 3.0.9](https://crates.io/crates/syn/3.0.9) | MIT OR Apache-2.0 | LICENSE-APACHE: `62c7a1e35f56406896d7aa7ca52d0cc0d272ac022b5d2796e7d6905db8a3636a`; LICENSE-MIT: `23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3` |
| [unicode-ident 1.0.27](https://crates.io/crates/unicode-ident/1.0.27) | (MIT OR Apache-2.0) AND Unicode-3.0 | LICENSE-APACHE: `62c7a1e35f56406896d7aa7ca52d0cc0d272ac022b5d2796e7d6905db8a3636a`; LICENSE-MIT: `23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3`; LICENSE-UNICODE: `f7db81051789b729fea528a63ec4c938fdcb93d9d61d97dc8cc2e9df6d47f2a1` |
| [vcpkg 0.2.15](https://crates.io/crates/vcpkg/0.2.15) | MIT/Apache-2.0 | LICENSE-APACHE: `60c93a31f490375aadf64098b75f10715010379541021e00261045d7800611d3`; LICENSE-MIT: `016d20f335060a70e79d9fcf8dfaa6201114d65d592211f4bdfb8ae9ca2bc1dc` |
| [zmij 1.0.23](https://crates.io/crates/zmij/1.0.23) | MIT | LICENSE-MIT: `23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3` |

SQLite 自身采用其 public-domain 声明，不能只按 Rust binding 的 MIT 处理；其来源版本和正文见 bundled `sqlite3.c` 开头及 [SQLite copyright](https://sqlite.org/copyright.html)。后续发布须包含适用的版权、许可和 NOTICE；本批只对本机合成测试构建进行记录。

更新路径：在 Node 自己的 manifest/lock 中提出明确版本差量，重新核对来源、许可、advisory、native 编译与事务测试；不运行无目标的全量升级。未执行联网 advisory 数据库扫描，不宣称不存在漏洞。
