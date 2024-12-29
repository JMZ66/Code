# 检查数字是否能填入某个位置
def is_valid(board, row, col, num):
    # 检查行中是否已经有 num
    for i in range(9):
        if board[row][i] == num:
            return False

    # 检查列中是否已经有 num
    for i in range(9):
        if board[i][col] == num:
            return False

    # 检查 3x3 小方格中是否已经有 num
    start_row = (row // 3) * 3
    start_col = (col // 3) * 3
    for i in range(3):
        for j in range(3):
            if board[start_row + i][start_col + j] == num:
                return False

    return True


# 回溯算法求解数独
def solve_sudoku(board):
    for row in range(9):
        for col in range(9):
            if board[row][col] == 0:  # 找到空格
                for num in range(1, 10):  # 尝试 1 到 9
                    if is_valid(board, row, col, num):
                        board[row][col] = num  # 填入 num

                        if solve_sudoku(board):  # 递归求解
                            return True
                        board[row][col] = 0  # 回溯
                return False
    return True


# 打印数独盘面
def print_board(board):
    for row in board:
        print(" ".join(str(num) if num != 0 else '.' for num in row))


# 测试数独盘面（0 表示未填的空格）
board = [
    [5, 3, 0, 0, 7, 0, 0, 0, 0],
    [6, 0, 0, 1, 9, 5, 0, 0, 0],
    [0, 9, 8, 0, 0, 0, 0, 6, 0],
    [8, 0, 0, 0, 6, 0, 0, 0, 3],
    [4, 0, 0, 8, 0, 3, 0, 0, 1],
    [7, 0, 0, 0, 2, 0, 0, 0, 6],
    [0, 6, 0, 0, 0, 0, 2, 8, 0],
    [0, 0, 0, 4, 1, 9, 0, 0, 5],
    [0, 0, 0, 0, 8, 0, 0, 7, 9]
]

# 打印未解的数独
print("未解数独:")
print_board(board)

# 求解数独
if solve_sudoku(board):
    print("\n解出的数独:")
    print_board(board)
else:
    print("无解的数独!")
