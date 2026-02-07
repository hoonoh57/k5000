# KOSPI Big10 IBS — 아키텍처 문서
> 최초 작성: 2026-02-07 | 최종 수정: 2026-02-07
> 버전: 1.1 | 상태: 검증 완료(백테스트), 실매매 연결 전

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

**알려진 위반:** `ui/workers.py`의 `AnalysisWorker`가 차트용 지표 재계산을 위해
`plugins.indicators`를 직접 import함. 향후 엔진이 지표 계산된 df를 반환하도록 개선 예정.

### 원칙 3: 하나의 파일 = 하나의 책임
파일 하나가 500줄을 넘으면 분리를 검토한다.
현재 가장 긴 파일: `ui/main_window.py`(약 550줄) — 분리 검토 필요.

### 원칙 4: 모든 데이터는 types.py의 타입으로
dict나 tuple을 모듈 간에 주고받지 않는다.
`Signal`, `TradeRecord`, `BacktestResult`, `Order` 등 명시적 타입을 사용한다.

**알려진 위반:** `ScreeningWorker`가 `Candidate` → `dict` 변환 후 UI에 전달.
향후 `Candidate` 타입을 직접 전달하도록 개선 예정.

### 원칙 5: 조립은 main.py에서만
어떤 플러그인을 사용할지, 어떤 파라미터를 쓸지는 오직 `main.py`에서 결정한다.
코어와 플러그인은 자신이 어떻게 조립되는지 모른다.

---

## 4. 파일 구조

Copy
E:\Kospi\kospi_big10_ibs │ ├── ARCHITECTURE.md ← 이 문서 (구조 변경 시 반드시 업데이트) ├── main.py ← 조립 지점 + CLI/UI 진입점 [자유 수정] │ ├── core/ ← 불변 코어 (수정 극도로 신중) │ ├── init.py │ ├── types.py ← 데이터 타입: Signal, TradeRecord 등 │ ├── interfaces.py ← 인터페이스: IDataSource, IIndicator 등 │ ├── event_bus.py ← 이벤트 발행/구독 │ ├── engine.py ← 백테스트 엔진 (strategy.py 로직 이식) │ ├── risk.py ← 서킷브레이커, 포지션사이징 │ ├── metrics.py ← 수익률, 샤프, MDD 계산 │ ├── order_types.py ← Order, BalanceItem, AccountInfo │ └── order_manager.py ← 주문 생애주기 관리 │ ├── config/ │ └── default_params.py ← 파라미터 + DB접속(환경변수) [자유 수정] │ ├── plugins/ ← 교체 가능 [자유 수정/추가/삭제] │ ├── init.py │ ├── indicators.py ← SuperTrend, JMA(VB.NET 포팅), RSI │ ├── signals.py ← ST+JMA 매수/매도 신호 │ ├── screener.py ← MySQL 베타/상관 스크리닝 │ ├── regime.py ← 시장 레짐 판단 (상승/하락/횡보) │ ├── data_source.py ← MySQL + Cybos + Kiwoom 폴백 │ └── broker_kiwoom.py ← 키움 브로커 어댑터 │ ├── ui/ ← UI [자유 수정] │ ├── init.py │ ├── main_window.py ← 메인 윈도우 (PyQt6) │ ├── chart_widget.py ← 6행 차트 (캔들+JMA 2색+매매신호+크로스헤어) │ └── workers.py ← QThread 워커 │ └── data/ └── logs/ ├── app.log └── error_log.txt


---

## 5. 데이터 흐름

(기존과 동일 — 변경 없음)

---

## 6. 매매 규칙 (검증 완료)

### 매수 조건
1. SuperTrend 상승추세 (st_dir == 1)
2. JMA 상승전환 (이전 기울기 ≤ 0 → 현재 > 0)
3. [선택] JMA 기울기 필터 (jma_slope_min > 0이면 적용)
4. [보조] ST가 상승전환되는 순간 + JMA 이미 상승 중

### 매도 조건
1. **손절**: ATR × 2.0 기반 동적 손절 (항상 작동)
2. **트레일링**: 목표수익(15%) 달성 후 최고가 대비 ATR × 2.5 하락 시
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

## 7. 확장 가이드

(기존과 동일 — 변경 없음)

---

## 8. 코어 수정이 필요한 경우

(기존과 동일 — 변경 없음)

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
- **AnalysisWorker 지표 재계산**: 엔진이 이미 계산한 지표를 차트용으로 다시 계산 (중복)
- **main_window.py 500줄 초과**: 분리 검토 필요

### 복잡도 경고
현재 파일 24개, 총 약 3,500줄. 이 수준은 관리 가능.
파일이 40개를 넘거나 총 줄 수가 8,000줄을 넘으면 구조 재검토.

---

## 10. 파라미터 기본값 (검증 완료)

| 파라미터 | 값 | 설명 |
|---------|---|------|
| st_period | 14 | SuperTrend ATR 기간 |
| st_multiplier | **3.0** | SuperTrend 배수 |
| jma_length | 7 | JMA 기간 |
| jma_phase | 50 | JMA 위상 |
| jma_power | 2 | JMA 거듭제곱 |
| rsi_period | 14 | RSI 기간 |
| rsi_fast | 5 | RSI 빠른 기간 |
| rsi_os | 35 | RSI 과매도 |
| rsi_ob | 80 | RSI 과매수 |
| target_profit_pct | **0.15** | 목표수익 **15%** |
| stop_loss_pct | -0.05 | 고정 손절 -5% |
| trailing_stop_pct | 0.08 | 트레일링 스톱 8% |
| use_atr_stops | True | ATR 동적 손절 사용 |
| atr_stop_mult | 2.0 | ATR 손절 배수 |
| atr_trailing_mult | 2.5 | ATR 트레일링 배수 |
| min_hold_days | 2 | 최소 보유일 |
| candidate_pool | 50 | 스크리닝 후보 수 |
| screen_top_n | 10 | 최종 선정 수 |
| screen_min_beta | 0.8 | 최소 베타 |
| screen_min_corr | 0.4 | 최소 상관 |
| initial_capital | 10,000,000 | 초기 자본 |

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

### ADR-004: DB 비밀번호 환경변수 전환 (2026-02-07)
- **상태**: 채택
- **맥락**: GitHub public 저장소에 비밀번호 노출 위험
- **결정**: `config/default_params.py`에서 `os.environ.get("DB_PASSWORD", "")` 사용
- **결과**: 로컬에서 `setx DB_PASSWORD "..."` 설정 필요

### ADR-005: 차트 전면 개선 (2026-02-07)
- **상태**: 채택
- **맥락**: 라인차트에서 JMA 구분 불가, 매매 신호 미표시, 마우스 인터랙션 없음
- **결정**: OHLC 캔들차트 + JMA 2색(상승/하락) + 매매신호 마커(▲/▼) + 크로스헤어(blitting)
- **결과**: JMA Slope를 퍼센트 변화율로 변환, 날짜 문자열 매칭으로 신호 마커 안정화

---

## 12. 변경 이력

| 날짜 | 버전 | 변경 내용 | 변경자 |
|------|------|----------|--------|
| 2026-02-07 | 1.0 | 최초 작성 | - |
| 2026-02-07 | 1.1 | 파라미터 실제값 반영, DB 환경변수 전환, 차트 개선 기록, 원칙 위반 사항 명시, 실행모드 설명 수정 | - |

---

## 부록 A: 빠른 참조

(기존과 동일)

## 부록 B: 실행 방법

```bash
# UI 모드 (기본)
cd E:\Kospi\kospi_big10_ibs
python main.py

# CLI 백테스트
set RUN_MODE=backtest
python main.py

# 환경변수 설정 (최초 1회)
setx DB_PASSWORD "your_password_here"
부록 C: 의존 패키지
Python 3.11+
PyQt6
numpy
pandas
matplotlib
pymysql
sqlalchemy
requests