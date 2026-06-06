// build.rs - siro-runtime
//
// 從 workspace 根的 proto/siro.proto 生成 Rust gRPC stubs
// 需要 protoc 3.x（https://grpc.io/docs/protoc-installation/）
//
// 執行：cargo build（會自動跑這個 build script）
// 產物：$OUT_DIR/siro.runtime.v1.rs（被 include!() 到 src/grpc.rs）

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let proto_dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()  // crates/
        .and_then(|p| p.parent())  // os-runtime/
        .expect("workspace root")
        .join("proto");

    let proto_file = proto_dir.join("siro.proto");

    // 確認 proto 檔存在（友善錯誤訊息）
    if !proto_file.exists() {
        return Err(format!(
            "proto 檔不存在：{}。請確認 proto/siro.proto 有存在。",
            proto_file.display()
        ).into());
    }

    println!("cargo:rerun-if-changed={}", proto_file.display());
    println!("cargo:rerun-if-changed=build.rs");

    tonic_prost_build::configure()
        .build_server(true)
        .build_client(true)
        .file_descriptor_set_path(std::path::PathBuf::from(std::env::var("OUT_DIR")?)
            .join("siro_descriptor.bin"))
        .compile_protos(&[proto_file], &[proto_dir])?;

    Ok(())
}
