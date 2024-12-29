from collections import defaultdict
from copy import deepcopy


# 初始化空格的候选值（1到9），并设置行、列、方块的约束
def initialize_domains(board):
    domains = defaultdict(set)
    for r in range(9):
        for c in range(9):
            if board[r][c] == 0:
                domains[(r, c)] = set(range(1, 10))
            else:
                domains[(r, c)] = {board[r][c]}
    return domains


# 检查给定值是否可以放入 (r, c)
def is_valid_assignment(board, r, c, num):
    for i in range(9):
        if board[r][i] == num or board[i][c] == num:
            return False

    start_row, start_col = 3 * (r // 3), 3 * (c // 3)
    for i in range(3):
        for j in range(3):
            if board[start_row + i][start_col + j] == num:
                return False

    return True


# 更新领域，利用 AC-3 算法保持弧一致性
def ac3(domains, board):
    queue = [(r, c) for r in range(9) for c in range(9) if board[r][c] == 0]

    while queue:
        r, c = queue.pop(0)
        if len(domains[(r, c)]) == 1:
            num = next(iter(domains[(r, c)]))
            for i in range(9):
                if i != c and num in domains[(r, i)]:
                    domains[(r, i)].remove(num)
                    if len(domains[(r, i)]) == 1:
                        queue.append((r, i))
                if i != r and num in domains[(i, c)]:
                    domains[(i, c)].remove(num)
                    if len(domains[(i, c)]) == 1:
                        queue.append((i, c))

            start_row, start_col = 3 * (r // 3), 3 * (c // 3)
            for i in range(3):
                for j in range(3):
                    if (start_row + i, start_col + j) != (r, c) and num in domains[(start_row + i, start_col + j)]:
                        domains[(start_row + i, start_col + j)].remove(num)
                        if len(domains[(start_row + i, start_col + j)]) == 1:
                            queue.append((start_row + i, start_col + j))
    return domains


# 启发式：选择最少剩余值的变量
def select_mrv_variable(board, domains):
    min_remaining = float('inf')
    selected = None
    for r in range(9):
        for c in range(9):
            if board[r][c] == 0 and len(domains[(r, c)]) < min_remaining:
                min_remaining = len(domains[(r, c)])
                selected = (r, c)
    return selected


# 回溯求解数独
def solve_sudoku(board):
    domains = initialize_domains(board)
    domains = ac3(domains, board)
    return backtrack(board, domains)


# 回溯算法，结合启发式搜索
def backtrack(board, domains):
    if all(board[r][c] != 0 for r in range(9) for c in range(9)):
        return True

    r, c = select_mrv_variable(board, domains)
    if r is None:
        return False

    for num in sorted(domains[(r, c)], key=lambda x: len(domains[(r, c)])):  # 启发式 LCV 排序
        if is_valid_assignment(board, r, c, num):
            board[r][c] = num
            backup_domains = deepcopy(domains)
            domains[(r, c)] = {num}
            domains = ac3(domains, board)
            if backtrack(board, domains):
                return True
            board[r][c] = 0
            domains = backup_domains

    return False


# 打印数独盘面
def print_board(board):
    for row in board:
        print(" ".join(str(num) if num != 0 else '.' for num in row))


# 测试数独盘面
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

print("未解数独:")
print_board(board)

if solve_sudoku(board):
    print("\n解出的数独:")
    print_board(board)
else:
    print("无解的数独!")
