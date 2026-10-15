# 角色评级客户端复核与全满账号重算

日期：2026-10-15。本轮直接读取港澳台正式客户端 1.0.1 (25) 的恢复元数据及 ARM64 代码，对照当前公式；不是仅用网站实现自证，也没有把静态复核写成手机实测。

## 结论

评级存在两个独立来源：个人评级只作用于该角色；全角色评级之和查总评级档位，所得固定值作用于每位上阵成员。未上阵角色参与总评级，跨过档位才改变共享加成。两项各自按三个能力维度加入基础值，然后留影、队长、歌曲属性、乐器、TGW 等百分比来源分别基于这个共同基数计算。当前 `formation-power.mjs` 已实现此顺序，本次没有修改公式或搜索实现。

发现的是此前性能样本的输入与“账号全满”不一致：基准使用所有角色评级 25、所有乐器等级 25。截图里的“评级 25 位／乐器 25 件”是记录数量，不能据此推断等级。当前正式数据的评级、乐器上限均为 50。

## 客户端证据

原始 `libil2cpp.so` SHA-256：`514a5b73d038c264b60cc91fd4a747cf178190c6b2096e6d7007c2020e2b1bca`，与此次正式评分数据记录的原生代码身份相同。CodeRegistration 为 `0xbdf4fa0`。使用已恢复的 v39 metadata 映射方法，再用 Capstone 读取对应原生指令。

| 客户端路径 | 地址 | 本次核对内容 |
|---|---|---|
| `Local.MemberCard.get_CharacterRank` | `0x5fae484` | 从当前玩家按本卡角色取评级；缺少角色时回退 1 |
| `Local.MemberCard.get_CharacterTotalRank` | `0x5fae570` | 转到全局玩家的总评级 getter，并不只求当前队伍之和 |
| `Local.Player.SetupCharacter` | `0x5fc03e4` | 遍历角色 Master，缺少角色则补入玩家角色集合 |
| `Local.Player.get_CharacterTotalRank` | `0x5fde604` | 对玩家角色集合选择各自评级并求和；泛型跳板 `0x72b28ec` 最终转到 `System.Linq.Enumerable.Sum` |
| 总评级选择器 | `0x6014ae0` | 读取每个角色的评级数据 |
| `CardParameterCalculator.GetCharacterRankBonus` | `0x55b9c04` | 按个人评级选择加成，转成三维相同的固定值 |
| `CardParameterCalculator.GetCharacterTotalRankBonus` | `0x55b9db8` | 按总评级选择共享加成，转成三维相同的固定值 |
| 两个档位谓词 | `0x55bcf38`、`0x55bcf80` | 比较输入评级大于等于档位，包含相等边界 |
| `CardPower.CreateSingleValue` | `0x55b9d4c` | 固定值乘 10000 存入三个维度，并非百分比 |
| `CalculateSlotPower` | `0x55bae98`、`0x55baf04` | 分别调用个人、总评级加成计算 |
| `CalculateSlotPower` 基数相加 | `0x55baffc`–`0x55bb06c` | 成员能力、个人评级、总评级、回忆经三次 `CardPower.op_Addition` 汇入栈上的共同基数 `sp+0x958` |

当前 25 位角色：全部评级 25 时总评级为 625，个人加成每维 120，总评级加成每维 60；全部评级 50 时总评级为 1250，个人加成每维 245，总评级加成每维 90。共享值查的是总评级对应档位，不是把每位角色的个人加成相加后送给全队。

原始客户端、恢复代码、元数据的摘要与反汇编保存在本地忽略目录 `output/verification/character-rank-20261015/native-source.json`、`native-disassembly.txt`、`native-rank-accessors.txt`。局部原生仿真的尝试在宿主退出 132，没有计为通过证据；以上客户端结论来自静态代码和 Master 核对。

## 控制变量重放与最优证明

使用与原性能样本相同的活动 2、Odd Dice EXPERT、67 张成员卡和 69 张留影、卡片满养成、TGW 21、回忆 0。先固定同一支队伍，仅改变账号输入：

| 角色评级 | 乐器等级 | 同一队伍最高分 |
|---|---|---:|
| 全 25 | 全 25 | 19,957,029 |
| 全 50 | 全 25 | 20,007,841 |
| 全 50 | 全 50 | 20,721,548 |

全满账号再次完整搜索，第一名仍为同一队伍，最高分 **20,721,548**，`bestProven=true`、`certifiedCount=1`、剩余差距 0。两次引擎耗时为 **32.37 s／28.96 s**，均展开 4594 个分支、精确阶段完整评分 6 支队伍；只证明第一名。结果比截图 20,443,752 高 277,796，但仅当截图的数据版本、回忆和其他条件也一致时，才能直接对比。这一结果不替代其他输入下的证书。

两次输入 SHA-256 均为 `25da4afed551229bdeb9154a5ce28f6405f23c77906b5aee7e149059ba557eb5`。原始结果为上述忽略目录中的 `all-max-proof.json`、`all-max-default-proof.json`。

## 修正与回归

基准工具默认使用与界面“一键满级”一致的账号预设，输出明确的账号参数；增加 `--account-preset fixed25`，保留原性能样本的复现方式。原 ABBA 的同输入速度结论继续有效，但它不是账号全满条件的计时。

新增回归核对未上阵角色跨档时每个槽位获得总评级加成、个人加成不会错误传播、上阵角色同时获得个人和共享加成，以及档位边界。与挑战优化器回归一起 **17/17 通过**。

```sh
node tools/benchmark_challenge_search.mjs \
  --data /private/tmp/otonote-current-event-inputs.json \
  --chart /private/tmp/otonote-10011103.json --event 2 \
  --evaluations 0 --time-limit-ms 120000 \
  --output output/verification/character-rank-20261015/all-max-default-proof.json

node --test site/tests/production-power.test.mjs site/tests/challenge-optimizer.test.mjs
```

此处证明仍限定于现有理想演出模型，完整比较 120 个技能顺序。测试、基准和文档均在本地完成，未部署。
