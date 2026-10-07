package com.transcriptplus.mobile.ui.transcript

import androidx.lifecycle.ViewModel
import com.transcriptplus.mobile.data.ProjectRepository
import com.transcriptplus.mobile.domain.Segment
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update

data class TranscriptState(val title: String, val segments: List<Segment>, val editing: Segment? = null)

class TranscriptViewModel(repository: ProjectRepository, projectId: String) : ViewModel() {
    private val project = repository.project(projectId)
    private val mutable = MutableStateFlow(TranscriptState(project?.title.orEmpty(), project?.segments.orEmpty()))
    val state: StateFlow<TranscriptState> = mutable

    fun beginEdit(segment: Segment) = mutable.update { it.copy(editing = segment) }
    fun cancelEdit() = mutable.update { it.copy(editing = null) }

    /** Empty text is rejected, matching the core's INVALID_DOCUMENT rule. */
    fun commitEdit(text: String) = mutable.update { current ->
        val editing = current.editing
        val trimmed = text.trim()
        if (editing == null || trimmed.isEmpty()) current
        else current.copy(
            segments = current.segments.map { if (it.id == editing.id) it.copy(text = trimmed) else it },
            editing = null,
        )
    }
}
