// build.rs - siro-ctl
//
// 從 proto/siro.proto 生成 Rust gRPC **client** stubs
// （siro-runtime 是 server + client、siro-ctl 只要 client）
//
// 需要 protoc 3.x（https://grpc.io/docs/protoc-installation/）

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 注意：build script 跑時是 runtime、不能用 env! 巨集（那是 compile-time）
    // 用 std::env::var 拿 Cargo 提供的環境變數
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR")
        .map_err(|e| format!("CARGO_MANIFEST_DIR not set: {}", e))?;
    let proto_dir = std::path::PathBuf::from(manifest_dir)
        .parent()  // crates/
        .and_then(|p| p.parent())  // os-runtime/
        .ok_or("無法推算 proto dir")?
        .join("proto");

    let proto_file = proto_dir.join("siro.proto");

    if !proto_file.exists() {
        return Err(format!(
            "proto 檔不存在：{}。請確認 proto/siro.proto 有存在。",
            proto_file.display()
        ).into());
    }

    println!("cargo:rerun-if-changed={}", proto_file.display());
    println!("cargo:rerun-if-changed=build.rs");

    // siro-ctl 只要 client（不要 server）
    tonic_prost_build::configure()
        .build_server(false)  // siro-ctl 是 client
        .build_client(true)
        .compile_protos(&[proto_file], &[proto_dir])?;

    Ok(())
}
