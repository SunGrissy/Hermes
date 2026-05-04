import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox
import os

def convert_excel_to_csv():
    # 初始化Tkinter并隐藏主窗口
    root = tk.Tk()
    root.withdraw()

    # 弹窗选择xlsx文件
    file_path = filedialog.askopenfilename(
        title="选择Excel文件",
        filetypes=[("Excel files", "*.xlsx *.xls")]
    )

    if not file_path:
        print("未选择文件，程序退出。")
        return

    try:
        # 获取文件名（不含扩展名）作为输出文件夹名
        file_name = os.path.splitext(os.path.basename(file_path))[0]
        output_dir = os.path.join(os.path.dirname(file_path), f"{file_name}_csv_output")
        
        # 创建输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 读取所有Sheet
        excel_data = pd.read_excel(file_path, sheet_name=None)

        counts = 0
        columns_to_remove = ["负责客服", "ID"]

        for sheet_name, df in excel_data.items():
            # 过滤掉指定的列（如果存在）
            df_filtered = df.drop(columns=[col for col in columns_to_remove if col in df.columns])
            
            # 生成CSV文件名
            csv_path = os.path.join(output_dir, f"{sheet_name}.csv")
            
            # 保存为CSV (utf-8-sig 以便Excel也能够正确识别中文)
            df_filtered.to_csv(csv_path, index=False, encoding='utf-8-sig')
            counts += 1

        messagebox.showinfo("成功", f"处理完成！\n共转换了 {counts} 个Sheet。\n保存路径：{output_dir}")
        print(f"成功转换 {counts} 个Sheet。保存位置: {output_dir}")

    except Exception as e:
        messagebox.showerror("错误", f"处理过程中发生错误：\n{str(e)}")
        print(f"发生错误: {e}")

if __name__ == "__main__":
    convert_excel_to_csv()
