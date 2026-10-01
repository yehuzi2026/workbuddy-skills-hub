version: "3.7"
# 开放签 - 独立部署包（与 /opt/wusun-app 完全隔离）
# 网络重命名为 kaifangqian_net，避免与宿主机其它 docker 栈的 mysql/redis 别名冲突
services:
  mysql:
    image: registry.cn-beijing.aliyuncs.com/kaifangqian/mysql:5.7.44
    hostname: kaifangqian-mysql
    volumes:
      - /home/data/kaifangqian/mysql:/var/lib/mysql
    deploy:
      mode: replicated
      replicas: 1
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M
    networks:
      kaifangqian_net:
        aliases:
          - mysql
    environment:
      # 密码由 deploy_to_server.py 在部署时注入（占位符，勿手填明文）
      - MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
      - TZ=Asia/Shanghai
  redis:
    image: registry.cn-beijing.aliyuncs.com/kaifangqian/redis:6.2.14
    hostname: kaifangqian-redis
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}
    deploy:
      mode: replicated
      replicas: 1
      resources:
        limits:
          memory: 128M
        reservations:
          memory: 64M
    networks:
      kaifangqian_net:
        aliases:
          - redis
networks:
  kaifangqian_net: null
