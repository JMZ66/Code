pub mod config;
pub mod extract;
pub mod fixturegen;
pub mod index;
pub mod matchdoc;
pub mod model;
pub mod query;
pub mod scan;
pub mod selftest;
pub mod service;
pub mod textutil;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
