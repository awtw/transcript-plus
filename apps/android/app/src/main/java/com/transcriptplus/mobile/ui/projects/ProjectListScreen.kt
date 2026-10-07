package com.transcriptplus.mobile.ui.projects

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.transcriptplus.mobile.R
import com.transcriptplus.mobile.domain.Project
import com.transcriptplus.mobile.domain.ProjectStatus
import com.transcriptplus.mobile.domain.formatTime

@Composable
fun ProjectListScreen(viewModel: ProjectListViewModel, onOpen: (Project) -> Unit) {
    val state by viewModel.state.collectAsState()
    var pendingDelete by remember { mutableStateOf<Project?>(null) }

    when (val current = state) {
        ProjectListState.Loading -> Box(Modifier.fillMaxSize(), Alignment.Center) { CircularProgressIndicator() }
        is ProjectListState.Loaded ->
            if (current.projects.isEmpty()) {
                Column(
                    Modifier.fillMaxSize().padding(24.dp),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(stringResource(R.string.empty_projects), style = MaterialTheme.typography.titleMedium)
                    Text(stringResource(R.string.empty_projects_hint), style = MaterialTheme.typography.bodyMedium)
                }
            } else {
                LazyColumn(Modifier.fillMaxSize()) {
                    items(current.projects, key = { it.id }) { project ->
                        ListItem(
                            modifier = Modifier.clickable { onOpen(project) },
                            headlineContent = { Text(project.title) },
                            supportingContent = { Text("${formatTime(project.durationMs)} · ${statusText(project.status)}") },
                            trailingContent = { TextButton({ pendingDelete = project }) { Text(stringResource(R.string.delete)) } },
                        )
                        HorizontalDivider()
                    }
                }
            }
    }

    pendingDelete?.let { project ->
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("刪除「${project.title}」？") },
            text = { Text("會同時刪除手機上的原始錄音副本，無法復原。") },
            confirmButton = {
                TextButton({ viewModel.delete(project); pendingDelete = null }) { Text(stringResource(R.string.delete)) }
            },
            dismissButton = { TextButton({ pendingDelete = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

// Status is always text, never colour alone.
private fun statusText(status: ProjectStatus): String = when (status) {
    ProjectStatus.Queued -> "等待處理"
    is ProjectStatus.Processing -> status.stage
    ProjectStatus.Completed -> "已完成"
    is ProjectStatus.Failed -> status.message
    ProjectStatus.Interrupted -> "已中斷，可重試"
}
