// src/lib.rs - siro-runtime 同時是 binary + library
//
// 設成 library 讓 integration test（tests/）能 import 內部 module。
// 對外（bridge / siro-ctl）不直接用、用 gRPC。

pub mod event_bus;
pub mod services;
pub mod supervisor;
pub mod grpc;

pub use grpc::generated as proto;
