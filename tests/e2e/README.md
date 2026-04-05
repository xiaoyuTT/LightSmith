# 端到端测试 (End-to-End Tests)

此目录包含 LightSmith 项目的端到端测试脚本。

## 测试覆盖

### test_docker_e2e.py

验证 Docker 部署后的完整流程：

1. **健康检查测试** - 验证后端服务是否正常启动
2. **SDK HTTP 上报测试** - 验证 SDK 能否成功上报数据到后端
3. **Trace 列表查询测试** - 验证 `GET /api/traces` API
4. **Trace 树形结构测试** - 验证 `GET /api/traces/{trace_id}` API 返回正确的树形 JSON
5. **高并发测试** - 验证 100 个并发 Run 无数据丢失

## 运行测试

### 前置条件

1. 启动 Docker 服务：
```bash
docker-compose up -d
```

2. 安装 Python SDK：
```bash
cd sdk && pip install -e .
```

### 执行测试

在**项目根目录**执行：

```bash
python tests/e2e/test_docker_e2e.py
```

### 预期输出

```
======================================================================
LightSmith P1.6 Docker E2E Test
======================================================================

[1/5] Testing health check endpoint...
[✓] Health check passed: {'status': 'ok', ...}

[2/5] Testing SDK HTTP transport...
[✓] SDK HTTP transport test passed

[3/5] Testing GET /api/traces...
[✓] List traces API test passed

[4/5] Testing GET /api/traces/{trace_id}...
[✓] Get trace tree API test passed

[5/5] Testing concurrent ingestion (100 runs)...
[✓] All 100 runs successfully ingested (no data loss)

======================================================================
Test Summary
======================================================================
[✓] Tree structure validation
[✓] Concurrent ingestion (100 runs)

[✓] All tests passed! P1.6 Docker deployment is working correctly.
```

## 故障排查

### 测试失败：Connection refused

**原因**：后端服务未启动或未就绪

**解决方案**：
```bash
# 检查服务状态
docker-compose ps

# 查看后端日志
docker-compose logs backend

# 重启服务
docker-compose restart backend
```

### 测试失败：No traces found

**原因**：SDK 上报失败或数据库为空

**解决方案**：
```bash
# 检查后端日志
docker-compose logs -f backend

# 手动测试 API
curl http://localhost:8000/api/traces

# 检查数据库
docker-compose exec postgres psql -U lightsmith -d lightsmith -c "SELECT COUNT(*) FROM runs;"
```

### 测试失败：并发测试未入库 100 条

**原因**：批量上报缓冲未 flush，或网络延迟

**解决方案**：
- 等待 5-10 秒后重新运行测试
- 批量上报的默认触发条件是 100 条或 5 秒，可能需要等待定时器触发

## 相关文档

- [Docker 部署指南](../../docs/DOCKER_DEPLOY.md)
- [P1 开发日志](../../execute/EXECUTE_P1.md)
- [项目 README](../../README.md)
