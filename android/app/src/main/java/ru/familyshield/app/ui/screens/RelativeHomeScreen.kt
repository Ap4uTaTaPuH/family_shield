package ru.familyshield.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ru.familyshield.app.di.AppContainer
import ru.familyshield.app.network.AlertMessage
import ru.familyshield.app.permissions.FullScreenIntentPermission
import ru.familyshield.app.permissions.PermissionChecker
import ru.familyshield.app.service.NotifyService
import ru.familyshield.app.ui.theme.AlertRed
import ru.familyshield.app.ui.theme.StatusOffline
import ru.familyshield.app.ui.theme.StatusOnline
import ru.familyshield.app.ui.viewmodel.RelativeHomeUiState
import ru.familyshield.app.ui.viewmodel.RelativeHomeViewModel

@Composable
fun RelativeHomeScreen(
    onOpenCallHistory: () -> Unit,
    onOpenRelativeRegister: () -> Unit,
    onOpenAlert: (String) -> Unit,
    onOpenCallDetail: (String) -> Unit,
    onOpenServerSettings: () -> Unit,
    onOpenBackgroundSetup: () -> Unit,
    onLogout: () -> Unit,
    authExpired: Boolean,
    onAuthExpiredAcknowledged: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: RelativeHomeViewModel = viewModel(factory = RelativeHomeViewModel.factory),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val serverConfigStore = AppContainer.serverConfigStore
    val fullScreenIntentSkipped by serverConfigStore
        .observeFullScreenIntentSkipped()
        .collectAsStateWithLifecycle(initialValue = false)

    // Пересчитываем на каждый ON_RESUME — пользователь может вернуться
    // с экрана системных настроек батареи или отозвать full-screen intent.
    var ignoringBattery by remember {
        mutableStateOf(PermissionChecker.check(context).ignoringBatteryOptimizations)
    }
    var canUseFullScreenIntent by remember {
        mutableStateOf(FullScreenIntentPermission.canUse(context))
    }
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                ignoringBattery = PermissionChecker.check(context).ignoringBatteryOptimizations
                canUseFullScreenIntent = FullScreenIntentPermission.canUse(context)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    LaunchedEffect(canUseFullScreenIntent, fullScreenIntentSkipped) {
        if (canUseFullScreenIntent && fullScreenIntentSkipped) {
            serverConfigStore.setFullScreenIntentSkipped(false)
        }
    }

    LaunchedEffect(authExpired) {
        if (!authExpired) {
            NotifyService.start(context)
        }
    }

    LaunchedEffect(authExpired) {
        if (authExpired) {
            snackbarHostState.showSnackbar("Сессия истекла, войдите заново")
            onAuthExpiredAcknowledged()
        }
    }

    LaunchedEffect(uiState.errorMessage) {
        val message = uiState.errorMessage ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(message)
        viewModel.clearError()
    }

    LaunchedEffect(uiState.pendingAlertCallId) {
        val callId = uiState.pendingAlertCallId.orEmpty()
        if (callId.isNotBlank()) {
            onOpenAlert(callId)
            viewModel.consumePendingAlert()
        }
    }

    Surface(modifier = modifier.fillMaxSize()) {
        Box(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                SnackbarHost(hostState = snackbarHostState, modifier = Modifier.fillMaxWidth())

                if (uiState.isLoading) {
                    CircularProgressIndicator()
                }

                if (!canUseFullScreenIntent) {
                    FullScreenIntentWarningCard(
                        skipped = fullScreenIntentSkipped,
                        onOpen = { FullScreenIntentPermission.openSettings(context) },
                    )
                }

                if (!ignoringBattery) {
                    BackgroundSetupWarningCard(onOpen = onOpenBackgroundSetup)
                }

                StatusCard(uiState = uiState)
                uiState.lastAlert?.let { alert ->
                    LastAlertCard(
                        alert = alert,
                        onOpenDetails = {
                            val callId = alert.callId
                            if (callId.isNotBlank()) {
                                onOpenCallDetail(callId)
                            }
                        },
                    )
                }
                PhoneCard(
                    phone = uiState.phone,
                    isSaving = uiState.isSavingPhone,
                    onPhoneChanged = viewModel::onPhoneChanged,
                    onSave = viewModel::savePhone,
                )

                Button(onClick = onOpenCallHistory, modifier = Modifier.fillMaxWidth()) {
                    Text(text = "История звонков")
                }

                if (!uiState.hasActiveLink) {
                    Button(onClick = onOpenRelativeRegister, modifier = Modifier.fillMaxWidth()) {
                        Text(text = "Привязать пенсионера")
                    }
                }

                Button(onClick = onLogout, modifier = Modifier.fillMaxWidth()) {
                    Text(text = "Выйти")
                }
            }

            TextButton(
                onClick = onOpenServerSettings,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(12.dp),
            ) {
                Text(text = "⚙")
            }
        }
    }
}

@Composable
private fun FullScreenIntentWarningCard(
    skipped: Boolean,
    onOpen: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFFFEBEE)),
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = if (skipped) "Полноэкранные тревоги пропущены" else "Полноэкранные тревоги выключены",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = Color(0xFFC62828),
            )
            Text(
                text = "На Android 14+ срочная тревога может не открыться поверх заблокированного экрана. " +
                    "Включите разрешение в системных настройках.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Button(
                onClick = onOpen,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(text = "Разрешить полноэкранные тревоги")
            }
        }
    }
}

@Composable
private fun BackgroundSetupWarningCard(onOpen: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFFFF3E0)),
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "Приложение может засыпать в фоне",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "Чтобы гарантированно получать тревоги, разрешите приложению работать в фоне.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Button(
                onClick = onOpen,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(text = "Настроить →")
            }
        }
    }
}

@Composable
private fun StatusCard(uiState: RelativeHomeUiState) {
    val connected = uiState.isNotifyRunning && uiState.isNotifyConnected
    val indicatorColor = when {
        uiState.isLoading -> StatusOffline
        connected -> StatusOnline
        else -> StatusOffline
    }
    val statusText = when {
        uiState.isLoading -> "Загрузка…"
        connected -> "Подключено к серверу"
        else -> "Нет подключения"
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(12.dp)
                        .clip(CircleShape)
                        .background(indicatorColor),
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = statusText,
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                )
            }
            Text(
                text = if (uiState.hasActiveLink) {
                    "Защищаем: ${uiState.linkedSeniorName.orEmpty()}"
                } else {
                    "Не привязан"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}


@Composable
private fun LastAlertCard(
    alert: AlertMessage,
    onOpenDetails: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = AlertRed,
            contentColor = Color.White,
        ),
    ) {
        Row(
            modifier = Modifier.padding(20.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Icon(
                imageVector = Icons.Default.Warning,
                contentDescription = null,
                modifier = Modifier.size(24.dp),
                tint = Color.White,
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    text = "Тревога",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                if (alert.timestamp.isNotBlank()) {
                    Text(
                        text = alert.timestamp,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
                Text(
                    text = alert.message.ifBlank { "Обнаружено возможное мошенничество" },
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(modifier = Modifier.height(4.dp))
                TextButton(
                    onClick = onOpenDetails,
                    colors = ButtonDefaults.textButtonColors(contentColor = Color.White),
                ) {
                    Text(text = "Подробности")
                }
            }
        }
    }
}

@Composable
private fun PhoneCard(
    phone: String,
    isSaving: Boolean,
    onPhoneChanged: (String) -> Unit,
    onSave: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = "Ваш номер для SMS",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            OutlinedTextField(
                value = phone,
                onValueChange = onPhoneChanged,
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                placeholder = { Text(text = "+7 900 000-00-00") },
            )
            Button(
                onClick = onSave,
                enabled = !isSaving,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(text = if (isSaving) "Сохраняю..." else "Сохранить")
            }
        }
    }
}
