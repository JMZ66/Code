"""界面、数据库和报告共用的分层名称。禁止把相似度写成鉴定。"""

CANDIDATE_LABEL = "谱库候选（未确认）"

LAYER_RAW = "原始信号"
LAYER_ALGORITHM = "算法结果"
LAYER_CANDIDATE = "谱库候选（未确认）"
LAYER_CONFIRMED = "确认结论"

DECISION_STANDARD = "standard_confirmed"
DECISION_MANUAL = "manual_review"
BASIS_STANDARD = "standard_rt_ri_spectrum"
BASIS_REVIEW = "reviewer_judgment"

DECISION_TEXT = {
    DECISION_STANDARD: "标准品确认",
    DECISION_MANUAL: "人工审核",
}

BASIS_TEXT = {
    BASIS_STANDARD: "标准品对照（保留时间/保留指数与谱图）",
    BASIS_REVIEW: "审核人判断",
}

PEAK_ALGO = "scipy-findpeaks-trapz"
PEAK_ALGO_VERSION = "1"
DECONV_ALGO = "eic-cluster-nnls"
DECONV_ALGO_VERSION = "1"
SIM_ALGO = "matchms.CosineGreedy"

DISCLAIMER = (
    "谱库相似度只是候选排序，不是化合物鉴定。"
    "确认结论只能来自标准品对照或审核人的明确操作，并记录操作者和时间。"
)
