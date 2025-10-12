// 全局变量
let socket;
let servers = {};
let reconnectAttempts = 0;
let maxReconnectAttempts = 10;
let reconnectDelay = 1000; // 初始重连延迟1秒
let reconnectTimer = null;

// DOM元素
const serversContainer = document.getElementById('servers');
const refreshBtn = document.getElementById('refreshBtn');
const configBtn = document.getElementById('configBtn');
const lastUpdateSpan = document.getElementById('lastUpdate');
const loadingDiv = document.getElementById('loading');
const configModal = document.getElementById('configModal');
const addServerForm = document.getElementById('addServerForm');
const serverList = document.getElementById('serverList');
const isLocalCheckbox = document.getElementById('isLocal');
const remoteFields = document.getElementById('remoteFields');

// 初始化应用
document.addEventListener('DOMContentLoaded', function() {
    initializeSocket();
    setupEventListeners();
});

// 初始化WebSocket连接
function initializeSocket() {
    // 配置Socket.IO选项
    socket = io({
        transports: ['websocket', 'polling'], // 优先使用websocket，降级到polling
        upgrade: true,
        rememberUpgrade: true,
        timeout: 20000,
        reconnection: true,
        reconnectionAttempts: maxReconnectAttempts,
        reconnectionDelay: reconnectDelay,
        reconnectionDelayMax: 5000,
        maxHttpBufferSize: 1e8
    });

    socket.on('connect', function() {
        console.log('已连接到服务器');
        reconnectAttempts = 0;
        reconnectDelay = 1000;
        hideLoading();

        // 清除任何现有的重连定时器
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
    });

    socket.on('disconnect', function(reason) {
        console.log('与服务器断开连接，原因:', reason);

        // 如果是服务器主动断开，不进行自动重连
        if (reason === 'io server disconnect') {
            showLoading('服务器断开连接，请刷新页面');
            return;
        }

        // 其他情况尝试自动重连
        scheduleReconnect('正在重新连接...');
    });

    socket.on('initial_data', function(data) {
        console.log('接收到初始数据:', data);
        updateServers(data);
    });

    socket.on('server_update', function(serverData) {
        console.log('服务器更新:', serverData);
        updateServer(serverData);
    });

    socket.on('servers_refreshed', function(serverDataList) {
        console.log('接收到服务器列表刷新:', serverDataList);
        console.log('当前页面服务器数量:', Object.keys(servers).length);
        console.log('接收到服务器数量:', serverDataList.length);

        // 强制清理现有服务器卡片
        serversContainer.innerHTML = '';
        servers = {};

        // 重新渲染所有服务器
        updateServers(serverDataList);

        console.log('页面更新完成，新服务器数量:', Object.keys(servers).length);
    });

    socket.on('connect_error', function(error) {
        console.error('连接错误:', error);
        scheduleReconnect(`连接失败 (${getReconnectMessage()})`);
    });

    socket.on('reconnect', function(attemptNumber) {
        console.log(`重连成功，尝试次数: ${attemptNumber}`);
        reconnectAttempts = 0;
        reconnectDelay = 1000;
    });

    socket.on('reconnect_attempt', function(attemptNumber) {
        console.log(`重连尝试 ${attemptNumber}/${maxReconnectAttempts}`);
    });

    socket.on('reconnect_failed', function() {
        console.error('重连失败，已达到最大尝试次数');
        showLoading('连接失败，请刷新页面重试');
    });
}

// 计划重连
function scheduleReconnect(message) {
    showLoading(message);

    // 清除现有定时器
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
    }

    // 如果达到最大重连次数，停止尝试
    if (reconnectAttempts >= maxReconnectAttempts) {
        showLoading('连接失败，请刷新页面重试');
        return;
    }

    // 设置重连定时器
    reconnectTimer = setTimeout(() => {
        reconnectAttempts++;

        // 指数退避策略
        const delay = Math.min(reconnectDelay * Math.pow(1.5, reconnectAttempts - 1), 10000);

        console.log(`尝试重连 (${reconnectAttempts}/${maxReconnectAttempts})，延迟: ${delay}ms`);

        // 手动触发重连
        if (socket && !socket.connected) {
            socket.connect();
        }

        reconnectDelay = delay;
    }, reconnectDelay);
}

// 获取重连消息
function getReconnectMessage() {
    if (reconnectAttempts === 0) return '网络连接异常';
    if (reconnectAttempts <= 3) return '网络不稳定，正在重连...';
    if (reconnectAttempts <= 6) return '网络连接较差，继续尝试...';
    return '网络连接异常，请检查网络...';
}

// 设置事件监听器
function setupEventListeners() {
    refreshBtn.addEventListener('click', function() {
        refreshData();
    });

    configBtn.addEventListener('click', function() {
        openConfigModal();
    });

    // 模态框关闭按钮
    const closeBtn = document.querySelector('.close');
    closeBtn.addEventListener('click', function() {
        closeConfigModal();
    });

    // 点击模态框外部关闭
    window.addEventListener('click', function(event) {
        if (event.target === configModal) {
            closeConfigModal();
        }
    });

    // 本地机器复选框变化
    isLocalCheckbox.addEventListener('change', function() {
        toggleRemoteFields();
    });

    // 添加服务器表单提交
    addServerForm.addEventListener('submit', function(e) {
        e.preventDefault();
        addServer();
    });
}

// 刷新数据
async function refreshData() {
    refreshBtn.disabled = true;
    refreshBtn.textContent = '刷新中...';

    try {
        const response = await fetch('/api/refresh', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (response.ok) {
            console.log('手动刷新成功');
        } else {
            console.error('刷新失败');
        }
    } catch (error) {
        console.error('刷新请求失败:', error);
    } finally {
        setTimeout(() => {
            refreshBtn.disabled = false;
            refreshBtn.textContent = '手动刷新';
        }, 1000);
    }
}

// 更新所有服务器数据
function updateServers(serverDataList) {
    serversContainer.innerHTML = '';

    serverDataList.forEach(serverData => {
        servers[serverData.host] = serverData;
        createServerCard(serverData);
    });

    updateLastUpdateTime();
}

// 更新单个服务器数据
function updateServer(serverData) {
    servers[serverData.host] = serverData;

    let serverCard = document.getElementById(`server-${serverData.host}`);
    if (serverCard) {
        updateServerCard(serverCard, serverData);
    } else {
        createServerCard(serverData);
    }

    updateLastUpdateTime();
}

// 创建服务器卡片
function createServerCard(serverData) {
    const card = document.createElement('div');
    card.className = 'server-card fade-in';
    card.id = `server-${serverData.host}`;

    const statusClass = getStatusClass(serverData.status);
    const statusText = getStatusText(serverData.status);

    card.innerHTML = `
        <div class="server-header">
            <div>
                <div class="server-name">${serverData.name}</div>
                <div class="server-host">${serverData.host}</div>
            </div>
            <span class="status-badge ${statusClass}">${statusText}</span>
        </div>

        <div class="server-content">
            ${renderServerContent(serverData)}
        </div>
    `;

    serversContainer.appendChild(card);
}

// 更新服务器卡片
function updateServerCard(card, serverData) {
    const statusBadge = card.querySelector('.status-badge');
    const content = card.querySelector('.server-content');

    const statusClass = getStatusClass(serverData.status);
    const statusText = getStatusText(serverData.status);

    statusBadge.className = `status-badge ${statusClass}`;
    statusBadge.textContent = statusText;

    content.innerHTML = renderServerContent(serverData);

    // 添加更新动画
    card.classList.add('fade-in');
    setTimeout(() => {
        card.classList.remove('fade-in');
    }, 500);
}

// 渲染服务器内容
function renderServerContent(serverData) {
    if (serverData.status === 'offline') {
        return `<div class="error-message">服务器离线</div>`;
    }

    if (serverData.status === 'error') {
        return `<div class="error-message">错误: ${serverData.error || '未知错误'}</div>`;
    }

    if (!serverData.devices || serverData.devices.length === 0) {
        return `<div class="error-message">未检测到${serverData.type === 'npu' ? 'NPU' : 'GPU'}设备</div>`;
    }

    let devicesHtml = '<div class="devices-list">';

    serverData.devices.forEach(device => {
        devicesHtml += renderDevice(device, serverData.type);
    });

    devicesHtml += '</div>';

    return devicesHtml;
}

// 渲染单个设备
function renderDevice(device, serverType) {
    const deviceType = serverType === 'npu' ? 'NPU' : 'GPU';

    return `
        <div class="device-item">
            <div class="device-header">
                ${deviceType} ${device.id}: ${device.name}
            </div>
            <div class="device-info">
                <div class="info-item">
                    <span class="info-label">温度:</span>
                    <span class="info-value ${getTempClass(device.temp)}">${device.temp || 'N/A'}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">功耗:</span>
                    <span class="info-value">${device.power || 'N/A'}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">显存:</span>
                    <span class="info-value">${device.memory_usage || 'N/A'}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">利用率:</span>
                    <span class="info-value ${getUtilClass(device.utilization)}">${device.utilization || 'N/A'}</span>
                </div>
            </div>
        </div>
    `;
}

// 获取状态样式类
function getStatusClass(status) {
    switch (status) {
        case 'online': return 'status-online';
        case 'offline': return 'status-offline';
        case 'error': return 'status-error';
        case 'connecting': return 'status-connecting';
        default: return 'status-offline';
    }
}

// 获取状态文本
function getStatusText(status) {
    switch (status) {
        case 'online': return '在线';
        case 'offline': return '离线';
        case 'error': return '错误';
        case 'connecting': return '连接中';
        default: return '未知';
    }
}

// 获取温度样式类
function getTempClass(temp) {
    if (!temp) return '';

    const tempValue = parseInt(temp);
    if (tempValue < 60) return 'temp-normal';
    if (tempValue < 80) return 'temp-warning';
    return 'temp-critical';
}

// 获取利用率样式类
function getUtilClass(utilization) {
    if (!utilization) return '';

    const utilValue = parseInt(utilization);
    if (utilValue < 30) return 'util-low';
    if (utilValue < 70) return 'util-medium';
    return 'util-high';
}

// 更新最后更新时间
function updateLastUpdateTime() {
    const now = new Date();
    const timeString = now.toLocaleString('zh-CN');
    lastUpdateSpan.textContent = `最后更新: ${timeString}`;
}

// 显示加载提示
function showLoading(message = '正在连接服务器...') {
    loadingDiv.style.display = 'flex';
    const loadingText = loadingDiv.querySelector('p');
    if (loadingText) {
        loadingText.textContent = message;
    }
}

// 隐藏加载提示
function hideLoading() {
    loadingDiv.style.display = 'none';
}

// 工具函数：格式化时间
function formatTime(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN');
}

// 工具函数：获取相对时间
function getRelativeTime(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;

    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);

    if (seconds < 60) return '刚刚';
    if (minutes < 60) return `${minutes}分钟前`;
    if (hours < 24) return `${hours}小时前`;

    return formatTime(dateString);
}

// 错误处理
window.addEventListener('error', function(e) {
    console.error('JavaScript错误:', e.error);
});

// 配置管理功能
function openConfigModal() {
    configModal.style.display = 'block';
    loadServerConfig();
}

function closeConfigModal() {
    configModal.style.display = 'none';
    addServerForm.reset();
    toggleRemoteFields();
}

function toggleRemoteFields() {
    if (isLocalCheckbox.checked) {
        remoteFields.style.display = 'none';
        // 清空所有远程字段
        clearAllFields();
    } else {
        remoteFields.style.display = 'block';
    }
}

function clearAllFields() {
    // 清空基础字段
    document.getElementById('serverPort').value = '22';
    document.getElementById('serverUsername').value = '';
    document.getElementById('serverPassword').value = '';
    document.getElementById('keyUsername').value = '';
    document.getElementById('keyFile').value = '';
    document.getElementById('keyPassword').value = '';

    // 清空跳板机字段
    document.getElementById('useBastion').checked = false;
    document.getElementById('bastionHost').value = '';
    document.getElementById('bastionPort').value = '22';
    document.getElementById('bastionUsername').value = '';
    document.getElementById('bastionPassword').value = '';
    document.getElementById('bastionKeyUsername').value = '';
    document.getElementById('bastionKeyFile').value = '';
    document.getElementById('bastionKeyPassword').value = '';

    // 重置字段显示
    toggleAuthFields();
    toggleBastionFields();
    toggleBastionAuthFields();
}

function toggleAuthFields() {
    const authType = document.getElementById('authType').value;
    const passwordFields = document.getElementById('passwordAuthFields');
    const keyFields = document.getElementById('keyAuthFields');

    if (authType === 'password') {
        passwordFields.style.display = 'block';
        keyFields.style.display = 'none';
    } else {
        passwordFields.style.display = 'none';
        keyFields.style.display = 'block';
    }
}

function toggleBastionFields() {
    const useBastion = document.getElementById('useBastion').checked;
    const bastionFields = document.getElementById('bastionFields');

    if (useBastion) {
        bastionFields.style.display = 'block';
    } else {
        bastionFields.style.display = 'none';
    }
}

function toggleBastionAuthFields() {
    const bastionAuthType = document.getElementById('bastionAuthType').value;
    const passwordFields = document.getElementById('bastionPasswordFields');
    const keyFields = document.getElementById('bastionKeyFields');

    if (bastionAuthType === 'password') {
        passwordFields.style.display = 'block';
        keyFields.style.display = 'none';
    } else {
        passwordFields.style.display = 'none';
        keyFields.style.display = 'block';
    }
}

async function loadServerConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        renderServerList(config.servers || []);
    } catch (error) {
        console.error('加载服务器配置失败:', error);
    }
}

function renderServerList(servers) {
    serverList.innerHTML = '';

    if (servers.length === 0) {
        serverList.innerHTML = '<p style="text-align: center; color: #666;">暂无服务器配置</p>';
        return;
    }

    servers.forEach(server => {
        const serverItem = document.createElement('div');
        serverItem.className = 'server-config-item';

        const localBadge = server.local || server.host === 'localhost' || server.host === '127.0.0.1'
            ? '<span class="local-badge">本地</span>'
            : '<span class="remote-badge">远程</span>';

        const typeBadge = server.type === 'npu'
            ? '<span class="npu-badge">NPU</span>'
            : '<span class="gpu-badge">GPU</span>';

        serverItem.innerHTML = `
            <div class="server-config-info">
                <h4>${server.name}${localBadge}${typeBadge}</h4>
                <p>主机: ${server.host}</p>
                ${!server.local && server.host !== 'localhost' && server.host !== '127.0.0.1'
                    ? `<p>用户: ${server.username || 'N/A'} | 端口: ${server.port || 22}</p>`
                    : ''}
            </div>
            <div class="server-config-actions">
                <button class="btn btn-danger btn-sm" onclick="deleteServer('${server.name}')">删除</button>
            </div>
        `;

        serverList.appendChild(serverItem);
    });
}

async function addServer() {
    const formData = new FormData(addServerForm);
    const serverData = {
        name: formData.get('name'),
        host: formData.get('host'),
        type: formData.get('type'),
        local: isLocalCheckbox.checked
    };

    // 如果不是本地机器，添加SSH配置
    if (!serverData.local) {
        serverData.port = parseInt(formData.get('port')) || 22;

        // 根据认证方式构建配置
        const authType = formData.get('authType');
        if (authType === 'password') {
            serverData.auth = {
                type: 'password',
                username: formData.get('username'),
                password: formData.get('password')
            };
        } else if (authType === 'key') {
            serverData.auth = {
                type: 'key',
                username: formData.get('keyUsername'),
                key_file: formData.get('keyFile'),
                key_password: formData.get('keyPassword') || null
            };
        }

        // 跳板机配置
        if (formData.get('useBastion')) {
            serverData.bastion = {
                host: formData.get('bastionHost'),
                port: parseInt(formData.get('bastionPort')) || 22
            };

            const bastionAuthType = formData.get('bastionAuthType');
            if (bastionAuthType === 'password') {
                serverData.bastion.auth = {
                    type: 'password',
                    username: formData.get('bastionUsername'),
                    password: formData.get('bastionPassword')
                };
            } else if (bastionAuthType === 'key') {
                serverData.bastion.auth = {
                    type: 'key',
                    username: formData.get('bastionKeyUsername'),
                    key_file: formData.get('bastionKeyFile'),
                    key_password: formData.get('bastionKeyPassword') || null
                };
            }
        }
    }

    try {
        const response = await fetch('/api/config/server', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(serverData)
        });

        const result = await response.json();

        if (response.ok) {
            alert('服务器添加成功');
            addServerForm.reset();
            toggleRemoteFields();
            loadServerConfig();
        } else {
            alert(`添加失败: ${result.error}`);
        }
    } catch (error) {
        console.error('添加服务器失败:', error);
        alert('添加服务器失败，请检查网络连接');
    }
}

async function deleteServer(serverName) {
    if (!confirm(`确定要删除服务器 "${serverName}" 吗？`)) {
        return;
    }

    console.log(`开始删除服务器: ${serverName}`);
    console.log('WebSocket连接状态:', socket ? (socket.connected ? '已连接' : '未连接') : '不存在');

    try {
        const response = await fetch(`/api/config/server/${encodeURIComponent(serverName)}`, {
            method: 'DELETE'
        });

        const result = await response.json();
        console.log('删除响应:', result);

        if (response.ok) {
            alert('服务器删除成功');

            // 等待一小段时间让后端处理完成，然后强制刷新
            setTimeout(() => {
                console.log('请求服务器刷新数据...');
                if (socket && socket.connected) {
                    socket.emit('request_servers');
                    console.log('已发送request_servers事件');
                } else {
                    console.log('WebSocket未连接，跳过事件发送');
                }

                // 重新加载配置
                loadServerConfig();
            }, 100);
        } else {
            alert(`删除失败: ${result.error}`);
        }
    } catch (error) {
        console.error('删除服务器失败:', error);
        alert('删除服务器失败，请检查网络连接');
    }
}

// 页面可见性变化处理
document.addEventListener('visibilitychange', function() {
    if (!document.hidden) {
        // 页面重新可见时，检查连接状态
        if (!socket || !socket.connected) {
            console.log('页面重新可见，检查连接状态');
            // 重置重连计数器并尝试连接
            reconnectAttempts = 0;
            reconnectDelay = 1000;

            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }

            if (socket) {
                socket.connect();
            } else {
                initializeSocket();
            }
        }
    }
});

// 网络状态变化处理
window.addEventListener('online', function() {
    console.log('网络已连接');
    if (!socket || !socket.connected) {
        reconnectAttempts = 0;
        reconnectDelay = 1000;
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        if (socket) {
            socket.connect();
        }
    }
});

window.addEventListener('offline', function() {
    console.log('网络已断开');
    showLoading('网络已断开，等待网络恢复...');
});