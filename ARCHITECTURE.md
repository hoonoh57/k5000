# KOSPI Big10 IBS — 아키텍처 문서
> 최초 작성: 2026-02-07 | 최종 수정: 2026-02-07
> 버전: 1.0 | 상태: 검증 완료(백테스트), 실매매 연결 전

---

## 1. 이 문서의 목적

이 문서는 프로젝트의 **설계 원칙, 파일 구조, 확장 규칙**을 기록합니다.
어떤 기능을 추가하거나 수정할 때 반드시 이 문서를 먼저 읽고,
수정 후에는 이 문서를 업데이트합니다.

**이 문서가 존재하는 이유:**
- 코드가 수천 줄로 늘어나도 "어디를 고쳐야 하는지" 즉시 찾기 위해
- 새 기능 추가 시 기존 로직을 깨뜨리지 않기 위해
- 6개월 뒤의 자신이 "왜 이렇게 했지?"를 이해하기 위해

---

## 2. 왜 이 구조로 바꿨는가 (의사결정 기록)

### 문제 상황
이전 `strategy.py` 단일 파일(약 1,200줄)로 잘 작동했으나:
- "코스피 하락장에서 이 전략이 무너지지 않느냐"는 근본 질문 제기
- 시장 레짐 판단, 인버스 전략, 실매매 주문/체결 등을 추가하면 3,000줄 이상 예상
- 한 줄 수정 시 전체 파일을 읽어야 하고, 편집 에러가 폭증

### 결정
"변하지 않는 부분(코어)"과 "변하는 부분(플러그인)"을 물리적으로 분리.
- 코어: 주문 생애주기, 리스크 관리, 성과 계산 등 → 어떤 전략이든 동일
- 플러그인: 지표, 신호, 스크리닝, 브로커 → 전략/증권사에 따라 교체

### 기각한 대안
| 대안 | 기각 이유 |
|------|----------|
| strategy.py에 계속 추가 | 3,000줄 이상 시 편집 에러 폭증, 부분 수정 불가능 |
| 마이크로서비스 분리 | 개인 프로젝트에 과도한 복잡도 |
| Backtrader/Zipline 도입 | 키움/사이보스 연동 불가, 한국 시장 특수성 미지원 |

---

## 3. 설계 원칙 (위반 금지)

### 원칙 1: 코어는 플러그인을 모른다
`core/` 폴더의 파일은 `plugins/`를 절대 import하지 않는다.
코어는 `interfaces.py`의 추상 클래스(IDataSource, IIndicator 등)만 안다.
구체 구현은 `main.py`(조립 지점)에서 주입한다.

### 원칙 2: 플러그인끼리 직접 호출 금지
`plugins/signals.py`가 `plugins/indicators.py`를 직접 호출하지 않는다.
엔진(`core/engine.py`)이 지표를 먼저 계산하고, 그 결과가 담긴 DataFrame을
신호 생성기에 전달한다.

### 원칙 3: 하나의 파일 = 하나의 책임
파일 하나가 500줄을 넘으면 분리를 검토한다.
현재 가장 긴 파일: `ui/main_window.py`(약 350줄), `core/engine.py`(약 300줄).

### 원칙 4: 모든 데이터는 types.py의 타입으로
dict나 tuple을 모듈 간에 주고받지 않는다.
`Signal`, `TradeRecord`, `BacktestResult`, `Order` 등 명시적 타입을 사용한다.

### 원칙 5: 조립은 main.py에서만
어떤 플러그인을 사용할지, 어떤 파라미터를 쓸지는 오직 `main.py`에서 결정한다.
코어와 플러그인은 자신이 어떻게 조립되는지 모른다.

---

## 4. 파일 구조

Copy
E:\Kospi\kospi_big10_ibs
│ ├── ARCHITECTURE.md ← 이 문서 (구조 변경 시 반드시 업데이트) ├── main.py ← 조립 지점 + CLI/UI 진입점 [자유 수정] │ ├── core/ ← 불변 코어 (수정 극도로 신중) │ ├── init.py │ ├── types.py ← 데이터 타입: Signal, TradeRecord 등 │ ├── interfaces.py ← 인터페이스: IDataSource, IIndicator 등 │ ├── event_bus.py ← 이벤트 발행/구독 │ ├── engine.py ← 백테스트 엔진 (strategy.py 로직 이식) │ ├── risk.py ← 서킷브레이커, 포지션사이징 │ ├── metrics.py ← 수익률, 샤프, MDD 계산 │ ├── order_types.py ← Order, BalanceItem, AccountInfo │ └── order_manager.py ← 주문 생애주기 관리 │ ├── config/ │ └── default_params.py ← 파라미터 + DB/서버 접속 정보 [자유 수정] │ ├── plugins/ ← 교체 가능 [자유 수정/추가/삭제] │ ├── init.py │ ├── indicators.py ← SuperTrend, JMA(VB.NET 포팅), RSI │ ├── signals.py ← ST+JMA 매수/매도 신호 │ ├── screener.py ← MySQL 베타/상관 스크리닝 │ ├── regime.py ← 시장 레짐 판단 (상승/하락/횡보) │ ├── data_source.py ← MySQL + Cybos + Kiwoom 폴백 │ └── broker_kiwoom.py ← 키움 브로커 어댑터 │ ├── ui/ ← UI [자유 수정] │ ├── init.py │ ├── main_window.py ← 메인 윈도우 (PyQt6) │ ├── chart_widget.py ← 6행 차트 │ └── workers.py ← QThread 워커 │ └── data/ └── logs/ ├── app.log └── error_log.txt


---

## 5. 데이터 흐름

[1. 조립] main.py │ ├─ CompositeDataSource (MySQL → Cybos → Kiwoom 자동 폴백) ├─ [SuperTrend, JMA, RSI] 지표 플러그인 ├─ STJMASignalGenerator 신호 생성기 ├─ STRegimeDetector 레짐 판단 ├─ RiskManager 리스크 관리 └─ BacktestEngine 엔진

[2. 스크리닝] BetaCorrelationScreener │ ├─ MySQL stock_base_info → KOSPI 대형주 시총 상위 50개 ├─ 각 종목 일봉 + KOSPI 지수 → 베타/상관 계산 └─ 베타 내림차순 상위 10개 반환

[3. 백테스트] BacktestEngine.run(code) │ ├─ data_source.fetch_candles(code) → 일봉 DataFrame ├─ for indicator in indicators: df = indicator.compute(df) ├─ signals = signal_gen.generate(df, code) └─ _simulate(df, signals) → BacktestResult │ ├─ 매일 포지션 상태 체크 ├─ ATR 동적 손절 + 트레일링 스톱 ├─ JMA 하락전환 시 수익/ST 분기 └─ 결과: 거래목록, 자본곡선, 성과지표

[4. 실매매] (향후) │ ├─ OrderManager.create_order() → 중복검사 → 리스크검증 → 전송 ├─ KiwoomBroker.send_order() → 키움 API └─ on_order_filled() → 잔고 갱신


---

## 6. 매매 규칙 (검증 완료)

### 매수 조건
1. SuperTrend 상승추세 (st_dir == 1)
2. JMA 상승전환 (이전 기울기 ≤ 0 → 현재 > 0)
3. [선택] JMA 기울기 필터 (jma_slope_min > 0이면 적용)
4. [보조] ST가 상승전환되는 순간 + JMA 이미 상승 중

### 매도 조건
1. **손절**: ATR × 2.0 기반 동적 손절 (항상 작동)
2. **트레일링**: 목표수익(7%) 달성 후 최고가 대비 ATR × 2.5 하락 시
3. **ST 하락반전**: 즉시 매도 (무조건)
4. **JMA 하락전환**:
   - 목표수익 달성 → 매도
   - 목표 미달 + ST 상승 중 → **보유 유지** (핵심 규칙)
   - 목표 미달 + ST 비상승 → 매도
5. **RSI 극단 과매수**(≥80) + JMA 약세 → 매도

### 검증 결과 (2025-08-11 ~ 2026-02-07)
- 10개 종목, 평균 수익률 +68.71%
- 9개 수익, 1개 손실(-5.12%)
- 평균 샤프 2.5+

---

## 7. 확장 가이드 — "이것을 추가하려면 어디를 고치나?"

### 7-1. 새 지표 추가 (예: VWAP)
plugins/indicators.py에 VWAPIndicator 클래스 추가
IIndicator 인터페이스 구현 (name(), compute())
main.py의 indicators 리스트에 추가
indicators = [..., VWAPIndicator()]
코어 수정: 없음

### 7-2. 새 매매 전략 추가 (예: 볼린저 밴드 전략)
plugins/signals_bollinger.py 파일 생성
ISignalGenerator 인터페이스 구현
main.py에서 signal_gen 교체
signal_gen = BollingerSignalGenerator()
코어 수정: 없음

### 7-3. 다른 증권사 연결 (예: 한국투자증권)
plugins/broker_hantoo.py 파일 생성
IBroker 인터페이스 구현
main.py에서 broker 교체
broker = HantooBroker(api_key=...)
코어 수정: 없음

### 7-4. 시장 레짐 기반 동적 전략
plugins/regime.py 수정 또는 새 파일
IRegimeDetector 인터페이스 구현
레짐별 파라미터 세트를 config/default_params.py에 추가
core/engine.py의 run()에서 레짐에 따라 파라미터 분기 → 이 경우 engine.py 수정 필요 (유일한 코어 변경) → ARCHITECTURE.md에 변경 사유 기록

### 7-5. 인버스 ETF / 숏 전략 추가
plugins/signals_inverse.py 파일 생성
plugins/screener_bear.py — 하락장용 스크리너
main.py에서 레짐에 따라 signal_gen 교체
코어 수정: 없음 (Direction.SELL을 숏 진입으로 재해석)

### 7-6. Walk-Forward 검증 추가
plugins/walk_forward.py 파일 생성
BacktestEngine.run()을 반복 호출하는 래퍼
코어 수정: 없음

---

## 8. 코어 수정이 필요한 경우 (극도로 신중)

코어를 수정해야 하는 상황은 제한적입니다:

| 상황 | 수정 대상 | 주의사항 |
|------|----------|---------|
| 새 타입 추가 | core/types.py | 기존 타입 변경 금지, 추가만 |
| 새 인터페이스 추가 | core/interfaces.py | 기존 인터페이스 변경 금지, 추가만 |
| 엔진 로직 변경 | core/engine.py | 기존 _simulate 보존, 새 메서드 추가 |
| 주문 흐름 변경 | core/order_manager.py | 7단계 흐름 순서 변경 금지 |

**코어 수정 절차:**
1. 이 문서의 "의사결정 기록" 섹션에 사유 추가
2. 변경 전 기존 테스트(CLI 백테스트) 통과 확인
3. 변경 후 동일 테스트 재실행하여 성과 차이 확인
4. 차이가 있으면 이 문서에 기록

---

## 9. 외부 전문가 관점 진단

### 구조적 강점 (유지)
- **인터페이스 계약 기반**: 플러그인이 ABC를 구현하므로 타입 안전성 확보
- **조립 분리**: main.py가 유일한 조립 지점, 의존성 방향 일관적
- **데이터 소스 폴백**: MySQL → Cybos → Kiwoom 3중 안전장치
- **주문 관리 불변화**: 어떤 전략이든 주문→체결→잔고 흐름은 동일

### 알려진 약점 (향후 보완)
- **Walk-Forward 검증 부재**: 6개월 1구간 백테스트만으로 과적합 위험
- **동시 포지션 미지원**: 현재 종목당 1포지션, 포트폴리오 동시 운용 미구현
- **EventBus 동시성**: 실매매 시 멀티스레드 환경에서 락 필요
- **데이터 검증 계층**: fetch_candles 반환값의 품질 검증이 엔진 내부에 혼재

### 복잡도 경고
현재 파일 24개, 총 약 3,000줄. 이 수준은 관리 가능.
파일이 40개를 넘거나 총 줄 수가 8,000줄을 넘으면 구조 재검토.

---

## 10. 파라미터 기본값 (검증 완료)

| 파라미터 | 값 | 설명 |
|---------|---|------|
| st_period | 14 | SuperTrend ATR 기간 |
| st_multiplier | 2.0 | SuperTrend 배수 |
| jma_length | 7 | JMA 기간 |
| jma_phase | 50 | JMA 위상 |
| target_profit_pct | 0.07 | 목표수익 7% |
| stop_loss_pct | -0.05 | 고정 손절 -5% |
| use_atr_stops | True | ATR 동적 손절 사용 |
| atr_stop_mult | 2.0 | ATR 손절 배수 |
| atr_trailing_mult | 2.5 | ATR 트레일링 배수 |
| min_hold_days | 2 | 최소 보유일 |
| candidate_pool | 50 | 스크리닝 후보 수 |
| screen_top_n | 10 | 최종 선정 수 |
| screen_min_beta | 0.8 | 최소 베타 |
| screen_min_corr | 0.4 | 최소 상관 |

---

## 11. 의사결정 기록 (ADR)

### ADR-001: 단일 파일에서 코어+플러그인 분리 (2026-02-07)
- **상태**: 채택
- **맥락**: strategy.py 1,200줄에서 레짐판단/주문관리 추가 시 3,000줄+ 예상
- **결정**: core/(불변 9파일) + plugins/(교체가능 7파일) + ui/(3파일) 분리
- **결과**: 검증 완료. 동일 데이터에서 삼성전자 69.52% → 69.46% (오차 0.06%)

### ADR-002: MySQL 우선 데이터 소스 (2026-02-07)
- **상태**: 채택
- **맥락**: 5년 일봉 2,100만 행이 MySQL에 있음
- **결정**: MySQL → Cybos → Kiwoom 순 폴백 구조
- **결과**: 50개 종목 스크리닝 1.4초, 10개 백테스트 3초

### ADR-003: 이전 strategy.py의 JMA를 VB.NET 완전 포팅 유지 (2026-02-07)
- **상태**: 채택
- **맥락**: 단순화된 JMA로 교체 시 SK스퀘어 135% → 49%로 하락
- **결정**: _JMACore 클래스에 VB.NET 적응형 변동성밴드 로직 완전 보존
- **결과**: 삼성전자 동일 수익률 복원 확인

---

## 12. 변경 이력

| 날짜 | 버전 | 변경 내용 | 변경자 |
|------|------|----------|--------|
| 2026-02-07 | 1.0 | 최초 작성 | - |
| | | | |

---

## 부록 A: 빠른 참조 — "이 파일은 뭘 하나?"

| 파일 | 한 줄 요약 | 수정 빈도 |
|------|-----------|----------|
| core/types.py | Signal, TradeRecord 등 데이터 구조 정의 | 거의 없음 |
| core/interfaces.py | IDataSource, IIndicator 등 계약 정의 | 거의 없음 |
| core/engine.py | 매일 포지션 체크하는 백테스트 루프 | 낮음 |
| core/risk.py | 서킷브레이커, ATR 포지션사이징 | 낮음 |
| core/metrics.py | 수익률/샤프/MDD 계산 | 거의 없음 |
| core/order_manager.py | 주문→체결→잔고 7단계 | 거의 없음 |
| core/order_types.py | Order, BalanceItem 타입 | 거의 없음 |
| core/event_bus.py | 이벤트 발행/구독 | 거의 없음 |
| config/default_params.py | 파라미터 기본값 + DB 접속 | 자주 |
| plugins/indicators.py | SuperTrend, JMA, RSI 계산 | 보통 |
| plugins/signals.py | 매수/매도 신호 생성 규칙 | 자주 |
| plugins/screener.py | 베타/상관 종목 스크리닝 | 보통 |
| plugins/regime.py | 시장 상승/하락/횡보 판단 | 보통 |
| plugins/data_source.py | MySQL+Cybos+Kiwoom 데이터 | 낮음 |
| plugins/broker_kiwoom.py | 키움 주문 실행 | 낮음 |
| ui/main_window.py | 메인 UI 레이아웃 | 보통 |
| ui/chart_widget.py | 6행 차트 그리기 | 보통 |
| ui/workers.py | 스크리닝/분석 QThread | 낮음 |
| main.py | 모든 것을 조립하는 진입점 | 자주 |

## 부록 B: 실행 방법

```bash
# CLI 백테스트 (기본)
cd E:\Kospi\kospi_big10_ibs
python main.py

# UI 모드
set RUN_MODE=ui
python main.py

# 이전 strategy.py 단독 실행 (호환 유지)
python strategy.py
부록 C: 의존 패키지
Python 3.11+
PyQt6
numpy
pandas
matplotlib
pymysql
sqlalchemy
requests

---
