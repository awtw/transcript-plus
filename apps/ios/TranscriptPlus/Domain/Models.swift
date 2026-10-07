import Foundation

/// Mirrors the Rust core / desktop contract: integer milliseconds, stable segment ids.
struct Segment: Identifiable, Equatable, Sendable {
    let id: String
    var startMs: Int
    var endMs: Int
    var text: String
    var speaker: String
}

enum ProjectStatus: Equatable, Sendable {
    case queued
    case processing(stage: String)
    case completed
    case failed(message: String)
    case interrupted
}

struct Project: Identifiable, Equatable, Sendable {
    let id: String
    var title: String
    var durationMs: Int
    var created: Date
    var status: ProjectStatus
    var segments: [Segment]
}

func formatTime(ms: Int) -> String {
    let total = max(0, ms) / 1000
    return String(format: "%02d:%02d", total / 60, total % 60)
}
