"""Persistent desktop navigation; page changes never recreate acquisition widgets."""
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

PAGES = (
    ("实验准备", "登记实验信息，恢复或填写设备参数，连接并检查数据。"),
    ("范式设置", "选择任务与试次，确认同步方式后开始实验；完整采集会保存数据并生成报告。"),
    ("采集监控", "观察实时信号、频谱和实验进度。"),
    ("记录与报告", "查看评估报告，补充记录信息并导出交付数据。"),
    ("高级设置", "调整显示性能，导出事件用于检查与分析。"),
)


def navigation_icon(index):
    """Small consistent line icons, independent of installed symbol fonts."""
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(2, 2)
    painter.setPen(QPen(QColor("#7dd3fc"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    if index == 0:
        painter.drawRoundedRect(5, 5, 14, 16, 2, 2)
        painter.drawLine(9, 3, 15, 3)
        painter.drawLine(9, 10, 15, 10)
        painter.drawLine(9, 15, 13, 15)
    elif index == 1:
        for x, y in ((6, 8), (12, 15), (18, 10)):
            painter.drawLine(x, 3, x, 21)
            painter.setBrush(QColor("#0f172a"))
            painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
    elif index == 2:
        for a, b in zip(((2, 13), (6, 13), (9, 5), (13, 20), (16, 10), (19, 13)),
                        ((6, 13), (9, 5), (13, 20), (16, 10), (19, 13), (22, 13))):
            painter.drawLine(QPointF(*a), QPointF(*b))
    elif index == 3:
        painter.drawRoundedRect(5, 3, 14, 18, 2, 2)
        for x, y in ((9, 15), (12, 11), (15, 8)):
            painter.drawLine(x, 17, x, y)
    else:
        painter.drawEllipse(4, 4, 16, 16)
        painter.drawEllipse(9, 9, 6, 6)
        for a, b in (((12, 1), (12, 4)), ((12, 20), (12, 23)), ((1, 12), (4, 12)), ((20, 12), (23, 12))):
            painter.drawLine(QPointF(*a), QPointF(*b))
    painter.end()
    return QIcon(pixmap)


def build_shell(window):
    root = QWidget()
    outer = QHBoxLayout(root)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    sidebar = QFrame()
    sidebar.setObjectName("navigationRail")
    sidebar.setFixedWidth(188)
    rail = QVBoxLayout(sidebar)
    rail.setContentsMargins(14, 26, 14, 18)
    brand = QLabel("NeuroScope")
    brand.setObjectName("brandTitle")
    rail.addWidget(brand)
    caption = QLabel("多设备脑电实验工作台")
    caption.setObjectName("muted")
    rail.addWidget(caption)
    rail.addSpacing(30)
    window.navigation = QListWidget()
    window.navigation.setObjectName("pageNavigation")
    window.navigation.setIconSize(QSize(22, 22))
    window.navigation.setSpacing(5)
    window.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    for index, (title, _) in enumerate(PAGES):
        item = QListWidgetItem(navigation_icon(index), "  " + title)
        item.setSizeHint(QSize(150, 48))
        window.navigation.addItem(item)
    rail.addWidget(window.navigation, 1)
    footnote = QLabel("本地采集\n独立刺激窗口")
    footnote.setObjectName("railFootnote")
    rail.addWidget(footnote)
    outer.addWidget(sidebar)

    content = QWidget()
    body = QVBoxLayout(content)
    body.setContentsMargins(24, 18, 24, 16)
    body.setSpacing(12)
    window.page_title = QLabel()
    window.page_title.setObjectName("appTitle")
    window.page_description = QLabel()
    window.page_description.setObjectName("muted")
    window.page_description.setWordWrap(True)
    body.addWidget(window.page_title)
    body.addWidget(window.page_description)
    status = QWidget()
    window._global_status_layout = QGridLayout(status)
    window._global_status_layout.setContentsMargins(0, 0, 0, 0)
    body.addWidget(status)
    window.pages = QStackedWidget()
    window.page_columns = {}
    for index in range(len(PAGES)):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QWidget()
        columns = QHBoxLayout(panel)
        columns.setContentsMargins(0, 0, 6, 0)
        columns.setSpacing(18)
        pair = []
        for _ in range(2):
            column = QVBoxLayout()
            column.setSpacing(14)
            column.setAlignment(Qt.AlignmentFlag.AlignTop)
            columns.addLayout(column, 1)
            pair.append(column)
        window.page_columns[index] = pair
        scroll.setWidget(panel)
        window.pages.addWidget(scroll)
    window._build_controls()
    # The live workspace uses all available width, retaining its original tabs.
    monitor = window._build_workspace()
    old = window.pages.widget(2)
    window.pages.removeWidget(old)
    old.deleteLater()
    window.pages.insertWidget(2, monitor)
    task_scroll = window.pages.widget(1)
    window.pages.removeWidget(task_scroll)
    task_page = QWidget()
    task_body = QVBoxLayout(task_page)
    task_body.setContentsMargins(0, 0, 0, 0)
    task_body.addWidget(task_scroll, 1)
    task_scroll.show()
    window.pages.insertWidget(1, task_page)
    prep_scroll = window.pages.widget(0)
    window.pages.removeWidget(prep_scroll)
    prep_page = QWidget()
    prep_body = QVBoxLayout(prep_page)
    prep_body.setContentsMargins(0, 0, 0, 0)
    prep_body.addWidget(prep_scroll, 1)
    prep_scroll.show()
    window.pages.insertWidget(0, prep_page)
    body.addWidget(window.pages, 1)

    dock = QFrame()
    dock.setObjectName("controlDock")
    controls = QVBoxLayout(dock)
    controls.setContentsMargins(16, 10, 16, 12)
    context_row = QHBoxLayout()
    window.experiment_context = QLabel()
    window.experiment_context.setObjectName("muted")
    window.experiment_context.setWordWrap(True)
    context_row.addWidget(window.experiment_context, 1)
    context_row.addWidget(window.stimulus_status, 1)
    window.stimulus_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    controls.addLayout(context_row)
    run_controls = QFrame()
    run_controls.setObjectName("controlDock")
    run_controls.setFixedHeight(64)
    actions = QHBoxLayout(run_controls)
    actions.setContentsMargins(16, 12, 16, 12)
    actions.setSpacing(10)
    for button in (window.stimulus_start_button, window.stimulus_stop_button):
        button.setMinimumHeight(38)
        actions.addWidget(button, 1)
    window.stimulus_start_button.setText("开始实验")
    window.stimulus_stop_button.setText("停止实验")
    window.stimulus_start_button.setObjectName("stimulusButton")
    window.stimulus_stop_button.setObjectName("stopButton")
    task_body.addWidget(run_controls)
    connection_panel = QFrame()
    connection_panel.setObjectName("controlDock")
    connection_layout = QVBoxLayout(connection_panel)
    connection_layout.setContentsMargins(16, 10, 16, 12)
    window.connection_detail = QLabel()
    window.connection_detail.setWordWrap(True)
    connection_layout.addWidget(window.connection_detail)
    connection_actions = QHBoxLayout()
    window.stop_button.setText("断开连接")
    window.save_connection_button = QPushButton("保存连接配置")
    window.save_connection_button.clicked.connect(window._save_connection_settings)
    for button in (window.start_button, window.stop_button, window.save_connection_button):
        button.setMinimumHeight(38)
        connection_actions.addWidget(button, 1)
    connection_layout.addLayout(connection_actions)
    window.settings_status = QLabel("保存后，下次打开自动恢复设备参数；不恢复连接状态。")
    window.settings_status.setObjectName("muted")
    window.settings_status.setWordWrap(True)
    connection_layout.addWidget(window.settings_status)
    prep_body.addWidget(connection_panel)
    body.addWidget(dock)
    outer.addWidget(content, 1)
    window.setCentralWidget(root)

    def switch_page(index):
        if index < 0:
            return
        window.pages.setCurrentIndex(index)
        window.page_title.setText(PAGES[index][0])
        window.page_description.setText(PAGES[index][1])

    def update_context():
        participant = window.participant_id.text().strip() or "未填写被试"
        window.experiment_context.setText(
            f"{participant}  ·  {window.source_select.currentText()}  ·  {window.paradigm_select.currentText()}"
        )

    window.navigation.currentRowChanged.connect(switch_page)
    window.participant_id.textChanged.connect(update_context)
    window.source_select.currentTextChanged.connect(update_context)
    window.paradigm_select.currentTextChanged.connect(update_context)
    window.navigation.setCurrentRow(0)
    update_context()
