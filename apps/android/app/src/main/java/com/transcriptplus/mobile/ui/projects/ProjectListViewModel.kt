package com.transcriptplus.mobile.ui.projects

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.transcriptplus.mobile.data.ProjectRepository
import com.transcriptplus.mobile.domain.Project
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

sealed interface ProjectListState {
    data object Loading : ProjectListState
    data class Loaded(val projects: List<Project>) : ProjectListState
}

class ProjectListViewModel(private val repository: ProjectRepository) : ViewModel() {
    val state: StateFlow<ProjectListState> = repository.projects
        .map<List<Project>, ProjectListState> { ProjectListState.Loaded(it) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ProjectListState.Loading)

    fun delete(project: Project) {
        viewModelScope.launch { repository.delete(project.id) }
    }
}
