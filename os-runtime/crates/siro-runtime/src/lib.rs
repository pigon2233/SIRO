// src/lib.rs - siro-runtime 同時是 binary + library
//
// 設成 library 讓 integration test（tests/）能 import 內部 module。
// 對外（bridge / siro-ctl）不直接用、用 gRPC。

pub mod config;
pub mod event_bus;
pub mod hardware;
pub mod services;
pub mod supervisor;
pub mod grpc;
// v1.5.3 Computer Control：SIRO 透過 gRPC 操控 OS
pub mod sandbox;
pub mod commands;
pub mod fs_ops;

pub use grpc::generated as proto;
