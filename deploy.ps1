# XPU Monitor K8s 部署脚本 (Windows PowerShell)

# 配置变量
$IMAGE_NAME = "xpu-monitor"
$IMAGE_TAG = "latest"
$REGISTRY = "your-registry.com"  # 如果有私有镜像仓库，修改这里
$NAMESPACE = "xpu-monitor"
$CONFIG_PATH = "D:\mnt\private\app\xpu-monitor"

function Write-ColorOutput($ForegroundColor) {
    $fc = $host.UI.RawUI.ForegroundColor
    $host.UI.RawUI.ForegroundColor = $ForegroundColor
    if ($args) {
        Write-Output $args
    }
    $host.UI.RawUI.ForegroundColor = $fc
}

function Write-Info {
    Write-ColorOutput Green "[INFO] $args"
}

function Write-Warn {
    Write-ColorOutput Yellow "[WARN] $args"
}

function Write-Error {
    Write-ColorOutput Red "[ERROR] $args"
}

# 检查配置文件是否存在
function Check-Config {
    Write-Info "检查配置文件目录: $CONFIG_PATH"

    if (-not (Test-Path $CONFIG_PATH)) {
        Write-Warn "配置目录不存在，创建目录: $CONFIG_PATH"
        New-Item -ItemType Directory -Path $CONFIG_PATH -Force | Out-Null
    }

    $serversJson = Join-Path $CONFIG_PATH "servers.json"

    if (-not (Test-Path $serversJson)) {
        Write-Warn "servers.json 不存在，创建默认配置文件"
        $defaultConfig = @{
            servers = @()
            llm_config = @{
                enabled = $false
                api_url = ""
                api_key = ""
                model = "gpt-3.5-turbo"
            }
        } | ConvertTo-Json -Depth 10

        Set-Content -Path $serversJson -Value $defaultConfig
        Write-Info "默认配置文件已创建: $serversJson"
        Write-Warn "请编辑此文件添加您的服务器配置"
    }
}

# 构建Docker镜像
function Build-Image {
    Write-Info "构建Docker镜像: ${IMAGE_NAME}:${IMAGE_TAG}"
    docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .
    Write-Info "镜像构建完成"
}

# 推送镜像到仓库
function Push-Image {
    if ($REGISTRY -ne "your-registry.com") {
        Write-Info "标记镜像: ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
        docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

        Write-Info "推送镜像到仓库: ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
        docker push "${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
        Write-Info "镜像推送完成"

        # 更新YAML中的镜像名称
        (Get-Content k8s-deployment.yaml) -replace "image: $IMAGE_NAME:latest", "image: $REGISTRY/$IMAGE_NAME:$IMAGE_TAG" | Set-Content k8s-deployment.yaml
    }
}

# 部署到K8s
function Deploy-K8s {
    Write-Info "部署到Kubernetes集群"

    # 检查kubectl
    try {
        kubectl version --client | Out-Null
    } catch {
        Write-Error "kubectl 未安装或不在PATH中"
        exit 1
    }

    # 检查集群连接
    try {
        kubectl cluster-info | Out-Null
    } catch {
        Write-Error "无法连接到Kubernetes集群"
        exit 1
    }

    # 应用配置
    Write-Info "应用Kubernetes配置"
    kubectl apply -f k8s-deployment.yaml

    Write-Info "等待部署完成..."
    kubectl rollout status deployment/xpu-monitor -n $NAMESPACE

    Write-Info "部署完成！"
    Write-Info "访问地址: http://xpu.dev.huawei.com"
}

# 查看状态
function Show-Status {
    Write-Info "查看部署状态"
    kubectl get all -n $NAMESPACE

    Write-Info "`n查看Pod日志:"
    kubectl logs -n $NAMESPACE -l app=xpu-monitor --tail=50 -f
}

# 卸载
function Uninstall {
    Write-Warn "卸载XPU Monitor"
    kubectl delete -f k8s-deployment.yaml
    Write-Info "卸载完成"
}

# 主函数
function Main {
    param(
        [Parameter(Position=0)]
        [ValidateSet("build", "push", "deploy", "status", "undeploy")]
        [string]$Command = "deploy"
    )

    switch ($Command) {
        "build" {
            Check-Config
            Build-Image
        }
        "push" {
            Push-Image
        }
        "deploy" {
            Check-Config
            Build-Image
            Push-Image
            Deploy-K8s
        }
        "status" {
            Show-Status
        }
        "undeploy" {
            Uninstall
        }
    }
}

# 执行主函数
Main $args
