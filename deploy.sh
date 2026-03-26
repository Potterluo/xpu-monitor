#!/bin/bash

# XPU Monitor K8s 部署脚本

set -e

# 配置变量
IMAGE_NAME="xpu-monitor"
IMAGE_TAG="latest"
REGISTRY="your-registry.com"  # 如果有私有镜像仓库，修改这里
NAMESPACE="xpu-monitor"
CONFIG_PATH="/mnt/private/app/xpu-monitor"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查配置文件是否存在
check_config() {
    echo_info "检查配置文件目录: $CONFIG_PATH"
    if [ ! -d "$CONFIG_PATH" ]; then
        echo_warn "配置目录不存在，创建目录: $CONFIG_PATH"
        sudo mkdir -p "$CONFIG_PATH"
        sudo chown -R $(whoami):$(whoami) "$CONFIG_PATH"
    fi

    if [ ! -f "$CONFIG_PATH/servers.json" ]; then
        echo_warn "servers.json 不存在，创建默认配置文件"
        cat > "$CONFIG_PATH/servers.json" << 'EOF'
{
  "servers": [],
  "llm_config": {
    "enabled": false,
    "api_url": "",
    "api_key": "",
    "model": "gpt-3.5-turbo"
  }
}
EOF
        echo_info "默认配置文件已创建: $CONFIG_PATH/servers.json"
        echo_warn "请编辑此文件添加您的服务器配置"
    fi
}

# 构建Docker镜像
build_image() {
    echo_info "构建Docker镜像: $IMAGE_NAME:$IMAGE_TAG"
    docker build -t $IMAGE_NAME:$IMAGE_TAG .
    echo_info "镜像构建完成"
}

# 推送镜像到仓库（可选）
push_image() {
    if [ "$REGISTRY" != "your-registry.com" ]; then
        echo_info "标记镜像: $REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
        docker tag $IMAGE_NAME:$IMAGE_TAG $REGISTRY/$IMAGE_NAME:$IMAGE_TAG

        echo_info "推送镜像到仓库: $REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
        docker push $REGISTRY/$IMAGE_NAME:$IMAGE_TAG
        echo_info "镜像推送完成"

        # 更新YAML中的镜像名称
        sed -i "s|image: $IMAGE_NAME:latest|image: $REGISTRY/$IMAGE_NAME:$IMAGE_TAG|g" k8s-deployment.yaml
    fi
}

# 部署到K8s
deploy() {
    echo_info "部署到Kubernetes集群"

    # 检查kubectl
    if ! command -v kubectl &> /dev/null; then
        echo_error "kubectl 未安装，请先安装kubectl"
        exit 1
    fi

    # 检查集群连接
    if ! kubectl cluster-info &> /dev/null; then
        echo_error "无法连接到Kubernetes集群"
        exit 1
    fi

    # 应用配置
    echo_info "应用Kubernetes配置"
    kubectl apply -f k8s-deployment.yaml

    echo_info "等待部署完成..."
    kubectl rollout status deployment/xpu-monitor -n $NAMESPACE

    echo_info "部署完成！"
    echo_info "访问地址: http://xpu.dev.huawei.com"
}

# 查看状态
status() {
    echo_info "查看部署状态"
    kubectl get all -n $NAMESPACE

    echo_info "\n查看Pod日志:"
    kubectl logs -n $NAMESPACE -l app=xpu-monitor --tail=50 -f
}

# 卸载
undeploy() {
    echo_warn "卸载XPU Monitor"
    kubectl delete -f k8s-deployment.yaml
    echo_info "卸载完成"
}

# 主函数
main() {
    case "${1:-deploy}" in
        build)
            check_config
            build_image
            ;;
        push)
            push_image
            ;;
        deploy)
            check_config
            build_image
            push_image
            deploy
            ;;
        status)
            status
            ;;
        undeploy)
            undeploy
            ;;
        *)
            echo "用法: $0 {build|push|deploy|status|undeploy}"
            echo ""
            echo "命令说明:"
            echo "  build    - 构建Docker镜像"
            echo "  push     - 推送镜像到仓库"
            echo "  deploy   - 完整部署（构建+推送+部署）"
            echo "  status   - 查看部署状态和日志"
            echo "  undeploy - 卸载应用"
            exit 1
            ;;
    esac
}

main "$@"
