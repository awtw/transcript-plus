//! Transcript Plus shared core. Ports the rules from `core/transcript_plus` (Python) so the mobile
//! apps behave exactly like the desktop one. Python tests are the reference for every behaviour here.
pub mod domain;
pub mod error;
pub mod export;
pub mod storage;
