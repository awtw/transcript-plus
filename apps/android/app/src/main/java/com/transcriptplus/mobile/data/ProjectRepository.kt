package com.transcriptplus.mobile.data

import com.transcriptplus.mobile.domain.Project
import com.transcriptplus.mobile.domain.ProjectStatus
import com.transcriptplus.mobile.domain.Segment
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update

/** The UI's only dependency on data. The Rust core (via UniFFI) will provide the real implementation. */
interface ProjectRepository {
    val projects: StateFlow<List<Project>>
    fun project(id: String): Project?
    suspend fun delete(id: String)
}

class InMemoryProjectRepository(initial: List<Project>) : ProjectRepository {
    private val state = MutableStateFlow(initial)
    override val projects: StateFlow<List<Project>> = state
    override fun project(id: String) = state.value.firstOrNull { it.id == id }
    override suspend fun delete(id: String) = state.update { list -> list.filterNot { it.id == id } }

    companion object {
        fun sample() = InMemoryProjectRepository(
            listOf(
                Project(
                    "p1", "週會錄音", 1_800_000, ProjectStatus.Completed,
                    listOf(
                        Segment("s1", 1_200, 4_600, "我們下週三要把新版本上線。", "小王"),
                        Segment("s2", 5_000, 8_400, "測試報告什麼時候可以給我？", "小李"),
                    ),
                ),
                Project("p2", "客戶訪談", 2_700_000, ProjectStatus.Processing("正在轉錄"), emptyList()),
                Project("p3", "語音備忘", 95_000, ProjectStatus.Interrupted, emptyList()),
            ),
        )
    }
}
