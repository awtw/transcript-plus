package com.transcriptplus.mobile.ui.transcript

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ListItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.transcriptplus.mobile.R
import com.transcriptplus.mobile.domain.formatTime

@Composable
fun TranscriptScreen(viewModel: TranscriptViewModel) {
    val state by viewModel.state.collectAsState()
    Column(Modifier.fillMaxSize()) {
        Text(state.title, modifier = Modifier.padding(16.dp))
        LazyColumn(Modifier.fillMaxSize()) {
            items(state.segments, key = { it.id }) { segment ->
                ListItem(
                    modifier = Modifier
                        .clickable { viewModel.beginEdit(segment) }
                        .semantics { contentDescription = "${formatTime(segment.startMs)}，${segment.speaker}，${segment.text}" },
                    overlineContent = { Text("${formatTime(segment.startMs)} · ${segment.speaker}") },
                    headlineContent = { Text(segment.text) },
                )
                HorizontalDivider()
            }
        }
    }
    state.editing?.let { segment ->
        var text by remember(segment.id) { mutableStateOf(segment.text) }
        AlertDialog(
            onDismissRequest = viewModel::cancelEdit,
            title = { Text(stringResource(R.string.edit_segment)) },
            text = { OutlinedTextField(text, { text = it }, minLines = 3) },
            confirmButton = {
                TextButton({ viewModel.commitEdit(text) }, enabled = text.isNotBlank()) { Text(stringResource(R.string.done)) }
            },
            dismissButton = { TextButton(viewModel::cancelEdit) { Text(stringResource(R.string.cancel)) } },
        )
    }
}
