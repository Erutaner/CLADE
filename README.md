<div align="center">

<br>

# 🧬 CLADE

### **C**losed-**L**oop **A**gentic **D**iscovery **E**ngine
### *for Machine Learning Research and Engineering*

<br>

*让你的 ML 项目像生物一样演化*

<br>

**Ji Zhang**

<sub>Harvard University &nbsp;·&nbsp; Nobody Funded Me Shit Lab</sub>

<sub><a href="mailto:jizhang@g.harvard.edu">jizhang@g.harvard.edu</a></sub>

<br>

![Python](https://img.shields.io/badge/Python-3.10+-3cc9b0?style=for-the-badge&logo=python&logoColor=white)
![Dependencies](https://img.shields.io/badge/依赖-零第三方库-5fd39a?style=for-the-badge)
![Modes](https://img.shields.io/badge/模式-Research%20%7C%20Engineering-d9b45b?style=for-the-badge)
![Setup](https://img.shields.io/badge/配置-全自然语言-b58cf5?style=for-the-badge)

<br>

<img src="assets/dashboard.png" alt="CLADE dashboard - 演化图谱" width="900">

<sub>内置仪表盘：单个自包含 HTML 文件，随演化进程自动刷新 · 图为示例数据</sub>

<br>

</div>

---

> 整日做横向干杂活，实验室卡都空着没空 research？
>
> 认真思考问题本质，想做个“大的”出来，却论文难产被导师怀疑天天摸鱼？
>
> 独自一人单挑一个方向，导师泉水挂机同门实习单飞，实验迟迟没有进度？
>
> 踏踏实实做研究，却只能看着隔壁流水线灌水天团拿下“故事会”大满贯？
>
> 自己实验室自古没发过几篇三大会，大家群龙无首，隔壁学校却有人一人投稿 40 篇 NIPS？

<div align="center">

### 停止焦虑，只要 Token 管够，CLADE 给您无限可能

</div>

---

## 📖 TL;DR

<table>
<tr><td width="130"><b>🔬 这是什么</b></td><td>

这是个零学习门槛和配置成本的，在真实工业和学术场景下取得过成绩的自动 ML 科学发现／工程迭代引擎，通过有向无环图组织不同范式和血缘关系的模型实验，用类似自然界生物演化的形式「演化」你的已有项目，驱动 agent 自动探索你已有模型的各种改进可能和与你当前思路完全不同的全新范式，来在指定数据集和任务上达到更好的效果。您的 agent 会自动地向引擎查询当前任务，完成任务，并提交任务供引擎核验，如此循环往复。

</td></tr>
<tr><td><b>👥 适合什么人群</b></td><td>

ML 领域的研究人员或工程师。引擎分为**科研模式**和**工程模式**，科研模式力主提出创新机制冲击 SOTA，工程模式对方法创新性要求较低，执行速度更快且成本更低，主要用于涨点。

</td></tr>
</table>

<br>

## 🎒 您需要有什么

### ✅ 必须

<br>

**1️⃣ 一个现成的 ML 项目代码**

> 即使它很不完善或者效果很差也没关系，引擎不会依赖你的方法，它会驱动 agent 在改进你方法的同时探索与你思路完全不同的新范式；代码有 bug 也没有关系，引擎会驱动 agent 修复直到跑通。

**2️⃣ 任意训练基础设施和访问方式**

> 可以是 AutoDL 等云平台，可以是您的本机 GPU，也可以是您的服务器或者公司内部 AIHUB，引擎会在配置阶段自动驱动 agent 全链路学习您的基础设施用法，遇到卡点会向您询问；引擎支持 coding agent 运行，数据集读入保存，GPU 计算和模型权重保存使用四个不同的平台，因此对绝大多数人的基础设施都适用，如果您的基础设施不适用它会在配置阶段告诉您，不会浪费您的时间和资源。

**3️⃣ 指定的数据集，任务和评测标准**

> 支持多数据集，多任务，多评测标准。

<br>

### 💡 推荐

> [!TIP]
> 一份您基础设施的使用方法文档，不需要事无巨细，但最好说一下常见的坑或卡点，这点尤其对于工业场景下一些临时搭建的，bug 较多的基础设施成立。如果您用的是 AutoDL 这类比较成熟，bug 少的平台或者自己服务器上的 GPU，那只需要提供访问方式即可。

<br>

## 🚀 三十秒启动

<div align="center">

| | |
|:---:|:---|
| **1** | 把 CLADE 项目压缩包下载到您的 ML 项目里的**任意路径** |
| **2** | 让自己的 coding 助手（比如 Codex、Claude Code 等）**解压** |
| **3** | 让它**阅读 `OPERATOR_PROMPT.md` 并演化当前项目** |

</div>

> **无需懂代码，无需敲命令，无需写配置文件。** 配置全部通过自然语言交互进行，引擎会问您它该知道的东西。

<br>

## ⭐ CLADE 相比类似项目的优势是什么

<br>

### ⚡ 1 · 30 秒内即可启动，跑在您自己的 agent 订阅上

无需懂代码，无需敲命令，无需写配置文件，只需把 CLADE 项目压缩包下载到您的 ML 项目里的任意路径，然后让自己的 coding 助手（比如 Codex，Claude Code 等）解压并阅读 `OPERATOR_PROMPT.md` 并演化当前项目即可。配置全部通过自然语言交互进行，引擎会问您它该知道的东西。

<br>

### 🏆 2 · 经过实践验证

CLADE **Engineering 模式**在我们的真实工业场景中改进了一个在亿级规模数据集上训练的推荐模型与其后训练方法，取得了 5 个月内纯模型侧改动带来的最大提升；CLADE **Research 模式**在我们的某个真实科研场景中刷新了 13 个开源数据集的 SOTA，其提出的机制能通过人类领域专家的创新性盲审。据我们所知，截至本项目开源，宣称达成此类效果的开源 auto research harness 非常少。出于保密原因，我们具体的场景不便透露。此外，由于在不同真实场景下长程运行过，很多坑我们都踩了，所以这个项目的使用体验可能会比你想象的好。

<br>

### 🔁 3 · 超长程运行

演化状态全部本地保存，网络中断，额度中断，甚至切换不同的 coding 助手（比如从 Codex 换到 Claude Code）都可以无缝衔接并恢复进度。

<br>

### 🧠 4 · 真正像人类 ML 科学家一样做研究

不同于其他的某些 auto research 项目用树结构或线性流水线组织实验，CLADE 不依赖您提供的初始思路，它会在改进您模型的同时探索与您思路不同的其他范式，用**有向无环图**而不是树表示整个探索路径。您的初始方案仅仅是其中一个根节点，其他根节点的范式血统与您的方案可能完全不同；此外，节点之间可以**杂交**以产生具备融合特性的子代，实验的成功或失败经验均会在图上**传播**，让 agent 越做越聪明。不同于大部分 auto research 项目（这些项目大都仅仅是驱动 agent 查阅文献写代码，或者简单地让 LLM 提出 idea 并派子 agent 查重），CLADE 对如何科学地进行研究创新，如何探索某种科学机制的有效性进行了非常精细的设计。

<br>

## ⚠️ CLADE 的局限

<br>

> [!WARNING]
> ### 💰 1 · Token 消耗量大
>
> 参考值：在我们的测试中，Claude MAX 20 倍会员的 Fable 5 周额度仅够迭代 4-5 个演化节点，Fable 5.1 周额度仅够迭代 2-3 个演化节点。如果您希望使用 CLADE 引擎驱动 Fable 不间断工作，可能需要 2-3 个 MAX 20 倍会员。因此我们推荐您在至少有一个 Codex／Claude Code 20 倍会员或同级别 Token 预算的情况下使用（不过，即使是三个会员账户也比人类工程师甚至研究生便宜的多）。

> [!WARNING]
> ### 📏 2 · 未在工业级 LLM 规模上验证
>
> 受限于我们的资源，我们没有对 CLADE 进行过演化工业级 LLM 或者类似规模的实验。我们在 Engineering 和 Research 模式下都仅对 7B 以下的深度学习模型进行过测试，测试时 GPU 调度规模在 16 张以下。任何 agent harness 都没法做到绝对可靠，如果您的资源比较紧张或者无法承受实验失败带来的损失，请谨慎使用。

> [!WARNING]
> ### 🤖 3 · 受基模能力限制
>
> 引擎最终能力受到您所使用的基模的限制。推荐使用指令遵循能力较强的前沿模型，如果您使用的 LLM 指令遵循能力较弱（例如经常做指令以外的无关事情或者幻觉式过度防御），引擎效果大概率会打折扣。

> [!CAUTION]
> ### 🚧 4 · 仍处在待完善阶段
>
> 这是一个还处在待完善阶段的项目，尽管我们进行了多场景下的长程测试（Research 模式下真实运行 1 个月，30+ 节点），CLADE 也自带多种修复机制，但运行中仍无法确保完全没有死锁等 bug。应当准许 agent 在由于引擎设计真实存在 bug 导致进入死锁时修改 CLADE 引擎代码，这也是我们为什么推荐使用前沿 LLM。

<br>

## 📄 许可证

本项目以 [MIT License](LICENSE) 开源 · Copyright © 2026 Ji Zhang

<br>

---

<div align="center">
<br>

**🧬 CLADE**

*Closed-Loop Agentic Discovery Engine for Machine Learning Research and Engineering*

<br>
</div>
