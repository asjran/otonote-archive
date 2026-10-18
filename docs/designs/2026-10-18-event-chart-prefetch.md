# 活动收益 Worker 的有界谱面预取

线上第一次完整活动收益运行暴露了本地缓存掩盖的网络瓶颈：Global700、70成员/73留影、360普通图+12挑战图，前250次Worker谱面请求串行累计283.933秒，中位单请求1067.4毫秒。旧默认节能运行在571.110秒取消，其中practical阶段452.293秒；这是未完成样本，不能宣称已完成最优性证明或据此计算完整任务提速倍数。原始线上记录位于仓库外 `/private/tmp/otonote-main-39118800710/browser-online/`。

本修复只并发读取和解析谱面，不并发评分、配队、证明或IndexedDB写入。评分公式、奖励公式、合法卡库、谱面范围、目标和证明条件均未变。

## 设计与边界

Worker先通过共用的 `eventYieldChartPlan` 取得原batch计划：full保持原 `seconds/id` 排序，quick保持原代表候选顺序；循环模式先挑战，再普通。共用函数是原代码逐字抽出，防止预取与真实消费顺序各自漂移。batch的其余执行逻辑不变。

`createBoundedChartLoader` 默认最多4个HTTP/JSON请求同时执行。第一次真正消费谱面时，优先调度该谱面，并只预取随后8个唯一URL。请求完成只消化当前窗口，不自动给整个卡库补满下载队列；下一次首次消费才推进窗口。已经消费过的缓存命中不推动窗口；后续首次miss仍按其实际位置建立新窗口。quick只建立quick元数据，未选full候选不会下载。

同一analysisDataUrl共享同一请求与解析结果，不修改返回内容。原来已消费谱面的每任务缓存继续保留以支持后续评分和group复用；新增的未消费预取条目最多8张，窗口跳转即释放旧的未消费条目，并中止旧的推测请求。正在被其他消费者await的谱面不会被窗口变更取消。

每项AbortController覆盖fetch和response.json，30秒截止；HTTP、JSON与网络错误沿原失败路径由实际消费者接收。尚未消费的预取promise始终settle为outcome，不发生无人处理的rejection，不凭推测失败把整个job判失败。任务正常result/error发出前，显式中止并等待剩余预取结束。显式signal abort同样关闭队列。UI的Worker.terminate仍使用浏览器原生命周期；它不运行JS finally，因此新包实际浏览器取消后网络是否全部结束仍需线上重验，不能用Node mock冒充。

没有预取整库Promise.all，也没有放宽并发上界或把评分移入多个Worker。请求本身的并发可能改变网络瞬时负荷；4并发/8窗口是保守固定值，没有把mock结果当实际CDN吞吐保证。

## 可复现验证

Node24.19.0，Apple M5。本地回归不运行真实评分搜索，只用受控异步fetch/JSON延迟及原实际Worker模块体；测试仅替换其batch/cache/proof进口，执行真实Worker加载器逻辑。另有真实batch+fake optimizer验证消费顺序与全域保留。

```sh
node --test site/tests/bounded-chart-loader.test.mjs site/tests/event-yield-chart-prefetch-worker.test.mjs site/tests/event-yield-batch.test.mjs
node site/tests/benchmark-event-chart-prefetch.mjs dad2cbaa24e5208037357c6d74e0d6ab76f7e1a1 /tmp/prefetch-abba.json
```

红测在原dad2cbaa实际Worker路径检测到最大并发1，报 `serial network bottleneck remains: max active 1`。25项轻量回归全部通过。绿测另覆盖无效未来URL不会污染当前合法加载，且实际访问无效URL仍报错；覆盖并发上限、只按需lookahead、URL去重、缓存hit后miss、跳窗时保留活动消费者、JSON阶段超时、HTTP/JSON失败、未消费失败无unhandled rejection、显式取消、result/error前关闭请求、challenge优先、quick不下载未选full以及真实quick/full原排序与全部候选保留。

ABBA使用同样24个URL、fetch固定10毫秒+JSON2毫秒、同消费顺序。旧Worker两次316.171/320.763毫秒，均值318.467毫秒；新Worker82.654/81.780毫秒，均值82.217毫秒。两侧都是24次请求、输出摘要完全相同，峰值并发由1变4。详见同目录JSON。

这些数字只是实际Worker路径的mock I/O回归（约74.2%墙钟减少），没有运行评分，不能当生产完整搜索提速。RSS字段是同一个温进程的运行后即时RSS，不是独立进程峰值，不据此下内存改善结论。展开数/完整评分数在该I/O基准不测、不填造为完整搜索指标。实际在线全难度耗时、峰值浏览器进程树RSS、第一名证书及terminate网络清理由发布后同输入浏览器验收继续补充。

正式候选门禁应加入新测试 `site/tests/bounded-chart-loader.test.mjs` 和 `site/tests/event-yield-chart-prefetch-worker.test.mjs`；已有event-yield-batch测试继续执行。此次任务分支提交不自行推送或部署。
