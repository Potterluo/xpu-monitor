@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal EnableExtensions EnableDelayedExpansion

:: 调试模式：如果需要调试，取消下面这行的注释
:: set DEBUG=1

if defined DEBUG (
    echo [调试] 脚本启动，当前目录：%CD%
    echo [调试] 脚本路径：%~dp0
)

goto :MAIN

:InitConfigPaths
if defined USERPROFILE (
    set "USER_CONFIG_DIR=!USERPROFILE!\.claude_config"
) else if defined HOMEDRIVE if defined HOMEPATH (
    set "USER_CONFIG_DIR=!HOMEDRIVE!!HOMEPATH!\.claude_config"
) else (
    set "USER_CONFIG_DIR=%~dp0\.claude_config"
)

set "USER_CONFIG_FILE=!USER_CONFIG_DIR!\claude_keys.txt"
exit /b 0

:EnsureConfigPath
call :InitConfigPaths
if not defined USER_CONFIG_DIR (
    echo [错误] 无法确定用户配置目录，回退到当前目录
    set "USER_CONFIG_DIR=%~dp0\.claude_config"
    set "USER_CONFIG_FILE=!USER_CONFIG_DIR!\claude_keys.txt"
)
if not exist "!USER_CONFIG_DIR!" (
    mkdir "!USER_CONFIG_DIR!" >nul 2>&1
    if errorlevel 1 (
        echo [错误] 无法创建目录：!USER_CONFIG_DIR!
        echo 请检查权限或手动创建后重试。
        pause
        exit /b 10
    )
)
exit /b 0

:CreateUserConfig
call :EnsureConfigPath
if exist "!USER_CONFIG_FILE!" exit /b 0
(
    echo # Claude Code - API 密钥文件模板
    echo # 在 "=" 后填写你的 API 密钥（无需引号）
    echo # 获取密钥地址：
    echo # GLM 密钥：https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys
    echo # GLM 套餐：https://bigmodel.cn/claude-code
    echo # Kimi 密钥：https://platform.moonshot.cn/console/api-keys
    echo # Qwen（百炼）密钥：https://bailian.console.aliyun.com/?apiKey=1
    echo # DeepSeek 密钥：https://platform.deepseek.com/api_keys
    echo.
    echo # GLM API
    echo glm_key=
    echo.
    echo # Kimi API
    echo kimi_key=
    echo.
    echo # Qwen（通过 DashScope）
    echo qwen_key=
    echo.
    echo # DeepSeek API
    echo deepseek_key=
) > "!USER_CONFIG_FILE!" 2>nul
if not exist "!USER_CONFIG_FILE!" (
    echo [错误] 无法创建配置文件：!USER_CONFIG_FILE!
    pause
    exit /b 11
)
exit /b 0

:OpenConfigEditor
call :EnsureConfigPath
call :CreateUserConfig
echo 正在打开配置文件...
if exist "!USER_CONFIG_FILE!" (
    start "" notepad "!USER_CONFIG_FILE!"
) else (
    echo [错误] 配置文件不存在且无法创建
    pause
    exit /b 12
)
echo 请在记事本中填写 API Key，保存后关闭记事本。
pause
goto :EOF

:EnsureKey
set "KEY_NAME=%~1"
set "KEY_VALUE="
for /f "usebackq tokens=1,* delims==" %%A in (`2^>nul findstr /B /C:"!KEY_NAME!=" "!USER_CONFIG_FILE!"`) do (
    set "KEY_VALUE=%%B"
)
if not defined KEY_VALUE (
    echo [提示] 未在 !USER_CONFIG_FILE! 中找到 !KEY_NAME!
    call :OpenConfigEditor
    exit /b 1
)
call set "%%KEY_NAME%%=%%KEY_VALUE%%"
exit /b 0

:MAIN
call :EnsureConfigPath
call :CreateUserConfig

echo 已加载配置：!USER_CONFIG_FILE!
echo.
echo ====== Claude Code 模型选择器 ======
echo.
echo  0: Claude^(官方默认^)
echo  1: GLM-4.6
echo  2: kimi-k2-turbo-preview
echo  3: Qwen3-Coder-Plus^(百炼^)
echo  4: DeepSeek-V3.2-Exp
echo  5: 安装/更新 Claude Code^(npm^)
echo  6: 配置 API 密钥
echo.

set /p "choice=输入编号 [0-6，回车=0]: "
if "!choice!"=="" set "choice=0"
set "choice=!choice: =!"

set "MODEL_NAME="
set "ANTHROPIC_BASE_URL="
set "ANTHROPIC_AUTH_TOKEN="
set "ANTHROPIC_MODEL="
set "ANTHROPIC_SMALL_FAST_MODEL="
set "API_TIMEOUT_MS="
set "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="

if "!choice!"=="0" (
    set "MODEL_NAME=Claude（官方）"
) else if "!choice!"=="1" (
    set "MODEL_NAME=GLM-4.6"
    call :EnsureKey glm_key
    if errorlevel 1 goto :MAIN
    set "ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic"
    set "ANTHROPIC_AUTH_TOKEN=!glm_key!"
    set "ANTHROPIC_MODEL=glm-4.6"
) else if "!choice!"=="2" (
    set "MODEL_NAME=kimi-k2-turbo-preview"
    call :EnsureKey kimi_key
    if errorlevel 1 goto :MAIN
    set "ANTHROPIC_BASE_URL=https://api.moonshot.cn/anthropic"
    set "ANTHROPIC_AUTH_TOKEN=!kimi_key!"
    set "ANTHROPIC_MODEL=kimi-k2-turbo-preview"
    set "ANTHROPIC_SMALL_FAST_MODEL=kimi-k2-turbo-preview"
) else if "!choice!"=="3" (
    set "MODEL_NAME=Qwen3-Coder-Plus（百炼）"
    call :EnsureKey qwen_key
    if errorlevel 1 goto :MAIN
    set "ANTHROPIC_BASE_URL=https://dashscope.aliyuncs.com/api/v2/apps/claude-code-proxy"
    set "ANTHROPIC_AUTH_TOKEN=!qwen_key!"
) else if "!choice!"=="4" (
    set "MODEL_NAME=DeepSeek-V3.2-Exp"
    call :EnsureKey deepseek_key
    if errorlevel 1 goto :MAIN
    set "ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic"
    set "ANTHROPIC_AUTH_TOKEN=!deepseek_key!"
    set "API_TIMEOUT_MS=600000"
    set "ANTHROPIC_MODEL=deepseek-reasoner"
    set "ANTHROPIC_SMALL_FAST_MODEL=deepseek-reasoner"
    set "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"
) else if "!choice!"=="5" (
    where npm >nul 2>nul
    if errorlevel 1 (
        echo [错误] 未找到 npm，请先安装 Node.js 18+
        pause
        goto :MAIN
    )
    echo 正在通过阿里镜像安装...
    call npm install -g @anthropic-ai/claude-code --registry=https://registry.npmmirror.com >nul 2>&1
    if errorlevel 1 (
        echo 切换官方源重试...
        call npm install -g @anthropic-ai/claude-code >nul 2>&1
        if errorlevel 1 (
            echo [失败] 请手动执行：npm install -g @anthropic-ai/claude-code
            pause
            goto :MAIN
        )
    )
    echo ✅ 安装成功！
    pause
    goto :MAIN
) else if "!choice!"=="6" (
    call :OpenConfigEditor
    goto :MAIN
) else (
    echo [错误] 无效输入：!choice!
    pause
    goto :MAIN
)

:: 检查 claude 是否可用
where claude >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 'claude' 命令，请先安装 CLI 工具
    echo 建议：npm install -g @anthropic-ai/claude-cli
    pause
    goto :MAIN
)

echo.
echo [启动] 模型：!MODEL_NAME!
if defined ANTHROPIC_BASE_URL echo 代理：!ANTHROPIC_BASE_URL!

:: 设置环境变量（供 claude 进程继承）
set "ANTHROPIC_BASE_URL=!ANTHROPIC_BASE_URL!"
set "ANTHROPIC_AUTH_TOKEN=!ANTHROPIC_AUTH_TOKEN!"
if defined ANTHROPIC_MODEL set "ANTHROPIC_MODEL=!ANTHROPIC_MODEL!"
if defined ANTHROPIC_SMALL_FAST_MODEL set "ANTHROPIC_SMALL_FAST_MODEL=!ANTHROPIC_SMALL_FAST_MODEL!"
if defined API_TIMEOUT_MS set "API_TIMEOUT_MS=!API_TIMEOUT_MS!"
if defined CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC set "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=!CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC!"

:: 启动 claude（同步等待）
call claude
set "rc=!ERRORLEVEL!"

echo.
echo [退出] 返回码=!rc!
if !rc! equ 0 (
    echo [成功] 正常退出
) else (
    echo [失败] 异常退出，请检查网络或密钥
)
pause
goto :MAIN