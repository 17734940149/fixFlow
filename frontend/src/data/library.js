// 这些正文来自原设计稿，作为接口数据样例保留；上传文件不会被替换成这些示例内容。
export const sampleDocuments = [
  { id: 'D001', fileName: '设备操作说明.pdf', name: '设备操作说明', stage: 'complete', uploadedAt: '2026-10-10 10:20', example: true },
  { id: 'D002', fileName: '设备维护记录.docx', name: '设备维护记录', stage: 'complete', uploadedAt: '2026-10-10 10:35', example: true },
]

export const sampleChunks = [
  { id: 'CH001', doc: 'D001', name: '1.2 设备铭牌与标识', answer: '设备铭牌包含型号、序列号及额定参数。\n查询相关资料时，应以铭牌标识为准。\n\n此处为文档原文块示例，不构成实际操作建议。', status: 'published', source: '设备操作说明.pdf · 第 2 页 · Chunk 01' },
  { id: 'CH002', doc: 'D001', name: '3.1 提示信息说明（旧内容）', answer: '提示信息出现在设备显示区域。相关释义见本章提示信息对照表。\n\n此处为待替换的旧文档段落示例。', status: 'published', source: '设备操作说明.pdf · 第 3 页 · Chunk 02' },
  { id: 'CH003', doc: 'D001', name: '3.1 提示信息说明（新内容）', answer: '提示信息应结合完整编号、出现时间及发生场景核对。相关释义以更新后的对照表为准。\n\n此处为与旧内容冲突的新文档段落示例。', status: 'pending', source: '设备操作说明.pdf · 第 5 页 · Chunk 03', conflict: 'CH002' },
  { id: 'CH004', doc: 'D001', name: '4.1 操作说明索引', answer: '本章按操作顺序列出说明条目，包含准备、启动及运行观察等章节索引。\n\n此处为文档原文块示例。', status: 'pending', source: '设备操作说明.pdf · 第 6 页 · Chunk 04' },
  { id: 'CH005', doc: 'D001', name: '4.2 使用说明章节', answer: '本节包含设备信息、操作条件与提示说明等内容。\n\n此处为已审核、尚未发布的文档原文块示例。', status: 'reviewed', source: '设备操作说明.pdf · 第 7 页 · Chunk 05' },
  { id: 'CH006', doc: 'D001', name: '附录 A 旧版说明', answer: '本附录为旧版说明内容。\n\n此处为已下架的文档原文块示例，不参与新检索。', status: 'offline', source: '设备操作说明.pdf · 第 8 页 · Chunk 06' },
  { id: 'CH007', doc: 'D001', name: '附录 B 设备标签字段', answer: '设备标签字段包括型号、序列号与参数信息。\n\n此处为待审核的文档原文块示例。', status: 'pending', source: '设备操作说明.pdf · 第 9 页 · Chunk 07' },
  { id: 'CH008', doc: 'D001', name: '附录 C 资料查询记录', answer: '资料查询记录包含完整提示、出现时间与发生场景。\n\n此处为已审核、尚未发布的文档原文块示例。', status: 'reviewed', source: '设备操作说明.pdf · 第 10 页 · Chunk 08' },
  { id: 'CH009', doc: 'D002', name: '2.1 维护记录字段', answer: '维护记录按时间保存，并关联设备标识与本次记录内容。\n\n此处为文档原文块示例。', status: 'reviewed', source: '设备维护记录.docx · 第 2 页 · Chunk 01' },
  { id: 'CH010', doc: 'D002', name: '2.2 维护资料清单', answer: '维护资料清单包括设备说明、历史记录及相关备注。\n\n此处为文档原文块示例。', status: 'pending', source: '设备维护记录.docx · 第 3 页 · Chunk 02' },
]

export const chunkStatuses = ['pending', 'reviewed', 'published', 'offline']
