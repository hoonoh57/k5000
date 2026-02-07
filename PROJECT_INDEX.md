
# KOSPI Big10 IBS — Project Index
## Version 1.0 | 2026-02-07

### 불변(IMMUTABLE) 코어 파일 — 수정 금지
| 파일 | 역할 |
|------|------|
| core/__init__.py | 코어 패키지 초기화 |
| core/types.py | Candle, Signal, TradeRecord, Regime 등 데이터 타입 |
| core/interfaces.py | IIndicator, ISignal, IDataSource, IBroker 등 인터페이스 |
| core/event_bus.py | 이벤트 발행/구독 버스 |
| core/engine.py | 백테스트 + 실매매 공통 루프 |
| core/risk.py | 리스크 관리: 서킷브레이커, 포지션사이징, 노출한도 |
| core/metrics.py | 성과 계산: 수익률, 샤프, MDD, 승률 등 |
| core/order_types.py | Order, BalanceItem, AccountInfo 등 주문/잔고 타입 |
| core/order_manager.py | 주문 생애주기: 생성→중복검사→리스크→전송→체결→잔고 |

### 교체 가능(PLUGIN) 파일 — 자유 수정/추가/삭제
| 파일 | 역할 |
|------|------|
| config/default_params.py | 전략 파라미터 기본값 |
| plugins/__init__.py | 플러그인 패키지 초기화 |
| plugins/indicators.py | SuperTrend, JMA, RSI 등 지표 계산 |
| plugins/signals.py | ST+JMA 매수/매도 신호 생성 |
| plugins/screener.py | 종목 스크리닝 로직 |
| plugins/regime.py | 시장 레짐(상승/하락/횡보) 판단 |
| plugins/data_source.py | 데이터 소스 어댑터 |
| plugins/broker_kiwoom.py | 키움증권 브로커 어댑터 |

### UI 파일 — 독립 교체 가능
| 파일 | 역할 |
|------|------|
| ui/__init__.py | UI 패키지 초기화 |
| ui/main_window.py | 메인 윈도우 |
| ui/chart_widget.py | 차트 위젯 (6 서브플롯) |
| ui/workers.py | QThread 워커 (스크리닝, 백테스트) |

### 진입점
| 파일 | 역할 |
|------|------|
| main.py | 앱 시작점, 조립(Composition Root) |

### 데이터/로그
| 경로 | 역할 |
|------|------|
| data/logs/error_log.txt | 런타임 에러 로그 |
