import "./load-env";

import { ingestFile } from "../src/lib/ingest";
import { seekdb } from "../src/lib/config";
import { stats } from "../src/lib/db/documents";
import { closePool } from "../src/lib/db/pool";
import { ensureReady } from "../src/lib/db/schema";

/**
 * 10 条测试笔记：机器学习 / 数据结构 / 操作系统。
 * 文本全部原创，走的是和页面上传完全一样的流水线：解析 -> 500 字切块 -> embedding -> 入库。
 */
interface SeedDocument {
  title: string;
  category: string;
  body: string;
}

const SEEDS: SeedDocument[] = [
  {
    title: "机器学习-过拟合与正则化",
    category: "课程资料",
    body: `过拟合指的是模型在训练集上表现很好，但在没见过的数据上明显变差：它把训练样本里的噪声也学成了规律。
判断方法是对比训练误差和验证误差，当验证误差先降后升、而训练误差持续下降时，曲线出现拐点，通常就已经开始过拟合了。
常见处理手段：增加数据量、做数据增强；降低模型复杂度，比如减少网络层数或决策树深度；加正则化项，L2 权重衰减把参数压小，L1 更容易得到稀疏参数；Dropout 在训练时随机丢弃神经元；提前停止 early stopping，在验证误差最低处停下；用交叉验证选超参。
欠拟合是相反的方向，训练误差本身就很高，这时应该加特征、加大模型或者减弱正则。`,
  },
  {
    title: "机器学习-偏差与方差",
    category: "课程资料",
    body: `泛化误差可以拆成偏差、方差和噪声三部分。偏差衡量模型假设与真实规律之间的系统差距，模型太简单时偏差高，表现为欠拟合。
方差衡量换一批训练数据后模型输出的波动，模型太复杂时方差高，表现为过拟合。二者通常此消彼长，调模型容量本质是在做偏差方差的权衡。
降低偏差：增加特征、提升模型容量、延长训练。降低方差：加数据、正则化、集成学习。Bagging 通过有放回采样并平均多个模型来降方差，Boosting 串行拟合残差主要降偏差，对噪声更敏感。`,
  },
  {
    title: "机器学习-评估指标笔记",
    category: "笔记",
    body: `准确率在类别不平衡时会骗人：负样本占 99% 的模型全预测负类也能拿到 99% 准确率，所以要结合精确率和召回率看。
精确率关心「预测为正的是不是真的正」，召回率关心「真的正样本被抓回来多少」。二者矛盾时用 F1 调和平均，或用 PR 曲线按业务代价选阈值。
ROC 曲线画的是真正率与假正率，AUC 表示随机取一正一负样本、模型给正样本更高分的概率，阈值无关。报告里不要同时堆 AUC 和准确率，要写清在哪个阈值下。`,
  },
  {
    title: "机器学习-梯度下降",
    category: "课程资料",
    body: `梯度下降沿损失函数负梯度方向迭代更新参数。批量梯度下降每步用全部数据，稳定但慢；随机梯度下降每步一个样本，噪声大却能跳出尖锐极小值；小批量介于两者之间，也最契合 GPU 的并行计算。
学习率是最重要的超参：太大震荡发散，太小收敛慢。带动量的方法累积历史梯度方向，抑制震荡；Adam 为每个参数自适应学习率，起步好用但对泛化不一定最优，训练后期常换 SGD+momentum 精调。
特征标准化能显著加快收敛，否则各维度梯度尺度差异大，等高线变成长椭圆。`,
  },
  {
    title: "机器学习-交叉验证",
    category: "笔记",
    body: `K 折交叉验证把数据切成 K 份，轮流用一份做验证、其余做训练，取 K 次指标的平均和标准差。标准差小说明结果稳定，大说明对数据划分敏感。
时间序列不能随机切分，要用滑动窗口或展开式验证，避免用未来数据预测过去造成数据泄漏。分层抽样保证每折的类别比例接近总体。
调参嵌套在外层，最终评估必须再用一层没参与过选择的数据，否则报告出来的分数是被选择过的乐观值。`,
  },
  {
    title: "数据结构-哈希表",
    category: "课程资料",
    body: `哈希表用哈希函数把键映射到下标，平均查找、插入、删除都是 O(1)，最坏退化到 O(n)。
冲突处理分两类：开放定址（线性探测、二次探测、双重哈希）把冲突项继续往后找空位，缺点是删除要留墓碑标记；链地址法在每个桶挂链表，负载因子超过阈值就扩容重建。
扩容一般取 2 的幂，元素数达到负载因子（常取 0.75）时翻倍重排。负载因子太高冲突变多，太低浪费空间。哈希函数要求雪崩性好，注意可变对象不要直接做键。`,
  },
  {
    title: "数据结构-平衡二叉树",
    category: "课程资料",
    body: `二叉搜索树中序遍历有序，但按有序数据插入会退化成链表，高度 O(n)。
AVL 树要求任意节点左右子树高度差不超过 1，插入删除后通过单旋或双旋恢复平衡，查找严格 O(log n)，旋转多、写入代价高，适合读多写少。
红黑树用颜色规则保证最长路径不超过最短路径两倍，靠染色加旋转，调整次数更少，写入更划算，所以 TreeMap、Linux 调度器多用它。B 树把多关键字放一个节点、降低高度，是数据库索引的首选。`,
  },
  {
    title: "数据结构-图的遍历与最短路",
    category: "笔记",
    body: `BFS 用队列，逐层扩展，能求无权图最短路；DFS 用栈或递归，适合判环、拓扑排序和连通分量，注意深度过大时递归爆栈要改显式栈。
Dijkstra 每次取距离最小的未确定节点松弛邻居，非负权正确，配小顶堆是 O((V+E) log V)；出现负权要用 Bellman-Ford，它还能检测负环。
Floyd 用三重循环求多源最短路，代码短但 O(V^3)。A* 在启发函数不高估剩余距离时最优，启发函数越接近真实代价扩展节点越少。`,
  },
  {
    title: "操作系统-进程调度算法",
    category: "课程资料",
    body: `先来先服务公平但平均等待时间长，长任务会让后面的短任务排队。短作业优先平均等待最短，却会饿死长任务，需要老化机制提高等待足够久的作业优先级。
时间片轮转用固定时间片保证响应性，片太大退化成长任务独享，太小则上下文切换开销占比过高。
多级反馈队列把优先级和时间片结合：新进程进高级队列，用完时间片降级，等待时再提升，兼顾吞吐与交互体验，是实际系统的常见做法。`,
  },
  {
    title: "操作系统-虚拟内存与页面置换",
    category: "课程资料",
    body: `虚拟内存用页表把逻辑地址映射到物理页，缺页时由内核从磁盘读入并建立映射，于是程序可以比物理内存大，多个进程也能共享同一份只读代码。
常见置换算法：FIFO 会抖动，Belady 异常下队列越长缺页反而越多；LRU 用最近使用时间，效果接近最优但硬件代价高；CLOCK 用访问位做环形扫描，是 LRU 的近似实现，代价低。
工作集模型统计一段时间内访问的页集合，据此给进程分配物理页，分配不足会持续缺页导致抖动，此时系统吞吐骤降。TLB 缓存地址翻译，命中才不用走页表，大页能减少 TLB 未命中。`,
  },
];

async function main(): Promise<void> {
  await ensureReady();
  console.log(`目标表：${seekdb.database}.${seekdb.table}`);
  console.log(`准备写入 ${SEEDS.length} 条测试笔记（走与页面上传相同的解析 / 切块 / embedding 流程）\n`);

  let totalChunks = 0;
  for (const seed of SEEDS) {
    const fileName = `${seed.title}.md`;
    const result = await ingestFile(fileName, Buffer.from(seed.body, "utf-8"), seed.category);
    totalChunks += result.chunks;
    console.log(
      `  + ${fileName.padEnd(34)} ${String(result.characters).padStart(4)} 字 → ${result.chunks} 块 → 写入 ${result.inserted} 行`,
    );
  }

  const counts = await stats();
  console.log(
    `\n本次 ${SEEDS.length} 个文件、${totalChunks} 个切块；表内现在共 ${counts.chunks} 行 / ${counts.files} 个文件 / ${counts.categories} 个分类。`,
  );
  console.log("下一步：npm run search:test");
}

main()
  .catch((error: unknown) => {
    console.error("种子数据写入失败：", error instanceof Error ? error.message : error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await closePool();
  });
