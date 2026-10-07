package com.transcriptplus.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.TextSnippet
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.transcriptplus.mobile.data.InMemoryProjectRepository
import com.transcriptplus.mobile.data.ProjectRepository
import com.transcriptplus.mobile.ui.projects.ProjectListScreen
import com.transcriptplus.mobile.ui.projects.ProjectListViewModel
import com.transcriptplus.mobile.ui.settings.SettingsScreen
import com.transcriptplus.mobile.ui.transcript.TranscriptScreen
import com.transcriptplus.mobile.ui.transcript.TranscriptViewModel

class MainActivity : ComponentActivity() {
    // Swap for the Rust-core backed repository here; nothing else in the UI layer changes.
    private val repository: ProjectRepository = InMemoryProjectRepository.sample()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { MaterialTheme { App(repository) } }
    }
}

private enum class Tab { Projects, Record, Settings }

@Composable
private fun App(repository: ProjectRepository) {
    val nav = rememberNavController()
    var tab by remember { mutableStateOf(Tab.Projects) }
    Scaffold(
        bottomBar = {
            NavigationBar {
                NavigationBarItem(tab == Tab.Projects, { tab = Tab.Projects },
                    { Icon(Icons.Filled.TextSnippet, null) }, label = { Text(stringResource(R.string.tab_projects)) })
                NavigationBarItem(tab == Tab.Record, { tab = Tab.Record },
                    { Icon(Icons.Filled.Mic, null) }, label = { Text(stringResource(R.string.tab_record)) })
                NavigationBarItem(tab == Tab.Settings, { tab = Tab.Settings },
                    { Icon(Icons.Filled.Settings, null) }, label = { Text(stringResource(R.string.tab_settings)) })
            }
        },
    ) { padding ->
        Box(Modifier.padding(padding)) {
            when (tab) {
                Tab.Projects -> NavHost(nav, startDestination = "projects") {
                    composable("projects") {
                        val vm: ProjectListViewModel = viewModel(factory = viewModelFactory {
                            initializer { ProjectListViewModel(repository) }
                        })
                        ProjectListScreen(vm) { nav.navigate("transcript/${it.id}") }
                    }
                    composable("transcript/{id}") { entry ->
                        val id = entry.arguments?.getString("id").orEmpty()
                        val vm: TranscriptViewModel = viewModel(key = id, factory = viewModelFactory {
                            initializer { TranscriptViewModel(repository, id) }
                        })
                        TranscriptScreen(vm)
                    }
                }
                Tab.Record -> Text(stringResource(R.string.record_consent))
                Tab.Settings -> SettingsScreen()
            }
        }
    }
}
