package com.transcriptplus.mobile.domain

import java.util.Locale

/** Mirrors the Rust core / desktop contract: integer milliseconds, stable segment ids. */
data class Segment(val id: String, val startMs: Int, val endMs: Int, val text: String, val speaker: String)

sealed interface ProjectStatus {
    data object Queued : ProjectStatus
    data class Processing(val stage: String) : ProjectStatus
    data object Completed : ProjectStatus
    data class Failed(val message: String) : ProjectStatus
    data object Interrupted : ProjectStatus
}

data class Project(
    val id: String,
    val title: String,
    val durationMs: Int,
    val status: ProjectStatus,
    val segments: List<Segment>,
)

fun formatTime(ms: Int): String {
    val total = maxOf(0, ms) / 1000
    return String.format(Locale.ROOT, "%02d:%02d", total / 60, total % 60)
}
