import sys
import os
import difflib
import argparse

def create_diff(file1_path, file2_path, output_path=None):
    """
    比较两个文件的内容，并生成差异报告。
    """
    # 1. 检查文件是否存在
    if not os.path.exists(file1_path):
        print(f"错误: 找不到文件 '{file1_path}'")
        return
    if not os.path.exists(file2_path):
        print(f"错误: 找不到文件 '{file2_path}'")
        return

    # 2. 读取文件内容
    try:
        with open(file1_path, 'r', encoding='utf-8') as f1:
            f1_lines = f1.readlines()
        with open(file2_path, 'r', encoding='utf-8') as f2:
            f2_lines = f2.readlines()
    except UnicodeDecodeError:
        print("错误: 文件编码读取失败，请确保文件是 UTF-8 编码。")
        return

    # 3. 生成差异 (HTML格式)
    # difflib.HtmlDiff 会生成一个包含表格的 HTML 页面，非常直观
    diff = difflib.HtmlDiff(wrapcolumn=80) # wrapcolumn 设置多少字符自动换行
    
    html_content = diff.make_file(
        f1_lines, 
        f2_lines, 
        fromdesc=f"Base: {os.path.basename(file1_path)}", 
        todesc=f"New: {os.path.basename(file2_path)}",
        context=True,  # True=只显示差异附近的行，False=显示全文
        numlines=5     # 差异上下文显示多少行
    )

    # 4. 生成简单的终端文本差异 (可选，用于快速查看)
    print("\n--- 简略文本差异预览 (详细请看 HTML 报告) ---")
    text_diff = difflib.unified_diff(
        f1_lines, 
        f2_lines, 
        fromfile=file1_path, 
        tofile=file2_path,
        lineterm=''
    )
    
    has_diff = False
    for line in text_diff:
        has_diff = True
        # 简单的着色 (如果终端支持)
        if line.startswith('+'):
            print(f"\033[92m{line}\033[0m") # 绿色
        elif line.startswith('-'):
            print(f"\033[91m{line}\033[0m") # 红色
        elif line.startswith('^'):
            print(f"\033[94m{line}\033[0m") # 蓝色
        else:
            print(line)
            
    if not has_diff:
        print("✅ 两个文件完全相同！")
        return

    # 5. 保存 HTML 报告
    if output_path is None:
        output_path = "diff_report.html"
        
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n✨ 详细的 HTML 对比报告已生成: {os.path.abspath(output_path)}")
    print("请使用浏览器打开该文件查看更好看的 Diff 视图。")


if __name__ == "__main__":
    # --- 如果你不懂命令行，请修改下面这两个路径 ---
    # 注意：Windows路径如果报错，可以在字符串前加 r，比如 r"D:\路径\..."
    
    file_a = r"D:\MyAgents\CCI-ScoreSystem\Dockerfile"  # 改成你的旧文件路径
    file_b = r"D:\MyAgents\CCI-ScoreSystem\Dockerfile-o"  # 改成你的新文件路径
    
    # ---------------------------------------------

    # 简单的检查，防止你忘了改路径导致报错
    if "main_old.py" in file_a and not os.path.exists(file_a):
        print("请先打开脚本代码，修改底部的 file_a 和 file_b 路径！")
    else:
        create_diff(file_a, file_b, "diff_report.html")