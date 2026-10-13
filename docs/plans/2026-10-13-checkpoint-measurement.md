# Checkpoint 阶段测量

## 背景与范围

继续 `2026-10-10-update-reliability-plan.md` 的 E。日服 12 并发恢复较基线从 1,228 秒降至 952 秒，但完整任务从 4,477 秒增至 4,729 秒。其中 checkpoint 从 805 秒增至 1,040 秒。两次生产代码和运行环境并非严格相同，不能据此归因于某一实现或宣称完整发布提速。

先在现有 checkpoint 返回值中增加分阶段计时、对象调用计数和进程峰值 RSS，再根据下一次真实有变化运行决定优化点。相比直接增加 checkpoint 并发或改状态格式，此步骤可以区分本地哈希、桶索引查询与网络传输的实际成本，也不改变恢复协议。

## 指标契约

`checkpointMetrics` 是结果 JSON 的附加字段，不写入远端 manifest、pointer 或复用证据。`checkpointed` 与 `unchanged` 都有指标；异常仍抛出原始错误，不伪造成功或部分计数。

| 字段 | 含义 |
| --- | --- |
| `prepareSeconds` | 参数、路径与工作集准备 |
| `inventorySeconds` | 本地盘点、首次哈希、清单序列化和对象去重 |
| `reuseLookupSeconds` | 恢复证据核对、远端列表确认及可复用对象统计 |
| `transferVerifySeconds` | 并发对象校验、必要上传及完整读回 |
| `sourceVerifySeconds` | 传输完成后的全部源文件再哈希和硬链接检查 |
| `commitSeconds` | 清单写入/读回、基线检查与必要的指针 CAS |
| `totalSeconds` | 从 checkpoint 入口到提交完成的墙钟时间 |
| `uniqueObjects` / `uniqueBytes` | 去重后的对象数量和字节数 |
| `logicalBytes` | 全部文件条目的逻辑字节数，包含重复内容和硬链接 |
| `verifiedReuseObjects` | 以本次恢复证据与新鲜远端版本验证器成功复用的对象数 |
| `objectVerifyCalls` / `objectPutCalls` | 对象适配器的校验/上传调用数；不含清单、指针、LIST 或 SDK 重试，不能当作 R2 计费请求数 |
| `uploadedBytes` | 本次确实新建的对象字节数，不含冲突后复用、控制对象和协议开销 |
| `peakResidentBytes` | Linux/macOS 当前 Python 进程生命周期峰值 RSS；不是整个 runner 或生产容器的峰值 |

各 worker 返回计数，由主线程 join 后汇总。Actions 摘要只允许已审阅的有限数值字段；布尔值、负数、非有限浮点数、异常大值和任意字符串均不展示。

## 保持的门禁与验证

- 保留完整源文件第二次哈希、硬链接关系校验、远端不可变对象读回和指针 CAS。
- 保留恢复证据的 bucket、ROOT、地区、清单及基线绑定；证据缺失时仍完整校验。
- 行为回归覆盖成功复用、新对象上传、无变化、缺失证据、远端损坏、源文件变化和指针冲突；计数与适配器实测调用对应。
- 新测试检查分阶段边界与摘要不泄漏任意字符串。相关 72 项本地回归通过；CI 和实际云端指标另行验收。

## 发布、验收与回退

独立 PR，仅增加测量。已核对 `tools/jp_update.py`：`r2_state.py` 属于生产依赖，因此合并本 PR 会让下一次双服探测进入完整生产。这是现有安全门禁的正常行为，不应为测量而放宽指纹边界。先以草稿 PR 保留，宜与下一批需要完整生产的变更一起安排合并。真实运行后读取 Actions 摘要，对两服分别比较各阶段时间、复用率与峰值内存。没有真实样本前不宣称 checkpoint 已加速，也不额外重复派发完整生产。

回退为还原本 PR；远端格式不变，现有 manifest、复用证据和公共版本不受影响。
