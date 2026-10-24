use std::process::ExitCode;
fn main() -> ExitCode {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() == 1 && args[0] == "capabilities" {
        println!("foundation=1 network=false security=false platform_unlock=false ready=false");
        ExitCode::SUCCESS
    } else {
        eprintln!(
            "Unavailable: connected control endpoint is not enabled; usage: radishlinkctl capabilities"
        );
        ExitCode::from(2)
    }
}
