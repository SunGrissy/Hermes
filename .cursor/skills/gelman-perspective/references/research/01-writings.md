# Agent 1: 著作与系统思考

## 核心著作

### 《Bayesian Data Analysis》(3rd ed, 2013)
- 与 Carlin, Stern, Dunson, Vehtari, Rubin 合著
- 贯穿全书的方法论：模型构建 → 后验推断 → 模型检查，三步循环
- 核心论点：贝叶斯分析不是计算后验概率选最优模型，而是用后验预测检查来发现模型的失败模式
- 信息来源：一手（本人著作），可信度：最高

### 《Regression and Other Stories》(2020)
- 与 Jennifer Hill, Aki Vehtari 合著
- 20 年教学和实践经验的凝结
- 强调回归分析的实际应用而非数学推导
- 信息来源：一手，可信度：最高

### 《Red State, Blue State, Rich State, Poor State》(2008)
- 将层次模型应用于政治科学
- 展示了分层看数据的威力——总体趋势和分组趋势可以完全相反
- 信息来源：一手，可信度：最高

## 核心论文

### "Philosophy and the Practice of Bayesian Statistics"（与 Shalizi 合著，2013）
- 挑战传统贝叶斯哲学：成功的贝叶斯统计更接近假说-演绎主义（hypothetico-deductivism）而非归纳学习
- 统计模型是"在演绎框架中进行归纳推理的工具"
- 后验概率是科学测量，不是主观信念声明
- 信息来源：一手，可信度：最高

### "The Garden of Forking Paths"（与 Loken 合著，2013）
- 解释为什么即使没有故意 p-hacking，研究者的分析自由度也会导致虚假发现
- 数据依赖的分析选择创造了大量可能的分析路径，膨胀了假阳性率
- 信息来源：一手，可信度：最高

### "Beyond Power Calculations: Type S and Type M Errors"（与 Carlin 合著，2014）
- Type S（符号）错误：统计显著结果方向错误的概率
- Type M（幅度）错误：效应大小被夸大的倍数
- 用"设计分析"替代传统统计功效分析
- 信息来源：一手，可信度：最高

### Statistical Workflow 论文
- 强调真实世界的数据分析是迭代过程：多个模型、多种数据类型的整合
- 经常被忽视的关键环节：测量（选择测什么）
- 原则跨越贝叶斯和频率主义框架
- 信息来源：一手，可信度：最高

## 反复出现的核心论点（≥3 次 = 真信念）

1. **模型检查比模型选择更重要**：出现在 BDA、博客、论文、访谈中
2. **统计显著性崇拜是科学的毒药**：博客、ClearerThinking 播客、Noah Smith 访谈、ASA p 值声明
3. **迭代工作流**：BDA、Workflow 论文、Stan 社区实践
4. **测量问题被严重低估**：Workflow 论文、博客、COVID 期间的批评
5. **对不确定性诚实**：贯穿所有著作和公开发言

## 自创术语
- Garden of Forking Paths（花园分叉路径）
- Type S / Type M Error
- Mister P（MRP - 多层回归与后分层）
- The Secret Weapon（多数据集估计值并排展示）
- Folk Theorem of Statistical Computing
- USA Today Fallacy
- Weakly Informative Priors
