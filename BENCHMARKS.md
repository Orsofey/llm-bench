# Какие бенчмарки смотреть в конце 2026 года

Ресёрч от 20.11.2026. Цифры лидеров меняются каждую неделю, а агрегаторы часто публикуют то, что заявили сами разработчики. Поэтому здесь нет таблиц «кто первый»: только **что** смотреть и **зачем**. Актуальные цифры берите на официальных страницах, они указаны в каждом разделе.

## 1. Что уже не различает сильные модели (насыщено)

| Бенчмарк | Почему не смотреть |
|---|---|
| MMLU, GSM8K, HumanEval, MBPP | У топовых моделей около 90–99%: разница между ними — шум |
| GPQA Diamond | Почти насыщен: лидеры набирают около 95% |
| OSWorld-Verified | По отзывам 2026 года уже плохо разделяет лучших агентов; на смену пришли OSWorld 2.0 и Terminal-Bench |

Если сервис хвастается высокими баллами именно здесь, это ничего не говорит о качестве.

## 2. Что ещё различает модели

### Код (ваш главный сценарий)
- **SWE-bench Pro** (Scale AI) — реальные задачи из репозиториев; пришёл на смену SWE-bench Verified. Есть очищенная версия SWE-Bench Pro Verified (arXiv 2609.08149).
- **Terminal-Bench 2.x** (tbench.ai) — агент работает в терминале: сборка, отладка, настройка окружения. Ближе всего к работе Claude Code.
- **LiveCodeBench / LiveCodeBench Pro** — постоянно обновляемые олимпиадные задачи, поэтому их труднее «выучить». v6 и Pro — разные варианты, сравнивать их нельзя.
- **DeepSWE, Vibe Code Bench** — длинные инженерные задачи и разработка веб-приложения целиком (2026).

### Агенты и инструменты (AI Agent: голосовое управление ПК)
- **BFCL v4** (Berkeley) — точность вызова функций.
- **τ²-bench** — многоходовые диалоги с инструментами; у топовых моделей pass^1 пока ниже 70%.
- **OSWorld 2.0 / OSWorld-Verified** — управление настоящим рабочим столом. Это ровно ваш сценарий.
- **GAIA** — многошаговые задачи ассистента.

### Рассуждение и знания
- **Humanity's Last Exam (HLE)** и **HLE-Diamond** (1000 вопросов, с сентября 2026) — самые сложные вопросы экспертного уровня.
- **ARC-AGI-2** (ARC Prize) — абстрактное мышление на новых задачах.
- **FrontierMath** — исследовательская математика.
- **MMLU-Pro** — замена MMLU с большим разбросом баллов.

### Русский язык
- **MERA Text 2.0** (сентябрь 2026, mera.a-ai.ru) — 12 закрытых тестов: ориентированные на человека, на культуру, агентные и на рассуждение. Тесты закрытые, поэтому их нельзя выучить заранее.
- **MERA Reason** (июль 2026) — рассуждение на русском: Luzitania, TMath, MMReD, ruAIME.

### Предпочтения людей
- **LMArena (Arena Elo)** — слепые сравнения пользователями. Хорошо показывает общее впечатление и плохо — точность.

## 3. Проверка подмены модели (научная база для «Подлинности»)

| Работа | Идея | Что взято в LLM Bench |
|---|---|---|
| *Are You Getting What You Pay For? Auditing Model Substitution in LLM APIs* (arXiv 2504.04715) | Формализует подмену. Простые тесты по одним текстам слабы: подмены на 20% запросов уже не видно | Не полагаемся на один сигнал, комбинируем несколько |
| *Model Equality Testing* (Gao и др.), *Rank-Based Uniformity Test* (arXiv 2506.06975) | Сравнение распределения ответов API с эталоном | Поведенческий отпечаток: распределение ответов при temperature=1 |
| *API-TAIL* (arXiv 2610.36801) | Выравнивание температуры и анализ «хвостов» распределения; ловит 10% подмены примерно за 200 запросов | Чтобы ловить частичную подмену, нужно больше выборок. Сейчас 24 запроса — грубый тест |
| *Contagious Fingerprints* (arXiv 2611.18104) | В длинных диалогах тесты дают ложные тревоги даже на честных моделях | Отпечатки снимаем только на коротких одиночных запросах |

**Главный вывод:** надёжнее всего «почерк» токенизатора. Его нельзя изменить, не подменив модель, и на него не влияет скрытая инструкция сервиса, если измерять **разницу** токенов. Поведенческие и качественные тесты дополняют его.

## 4. Что из этого есть в LLM Bench

| Нужно вам | Что сделано | Чего не хватает |
|---|---|---|
| Код | 6 базовых + 3 сложные задачи, код запускается на тестах | Задачи уровня репозитория (как SWE-bench Pro) |
| Рассуждение | 7 сложных задач с проверкой | — |
| Агент | 5 голосовых команд → вызовы инструментов | Многошаговые сценарии (как τ²-bench), понимание скриншотов (как OSWorld) |
| Монтаж | ffmpeg с реальным рендером, SRT, отбор дублей | — |
| Подлинность ключа | токенизатор, поведение, учёт токенов, скрытая инструкция, формат API | Встроенные эталоны Claude/Gemini: их надо снять с официального ключа |

## Источники
- [LLM Benchmarks Compared (LXT, 2026)](https://www.lxt.ai/blog/llm-benchmarks/)
- [Frontier AI Models Evaluation Benchmarks](https://kharshit.github.io/blog/frontier-ai-models-evaluation-benchmarks/)
- [The 2026 LLM Benchmark Reference](https://benchmarkingagents.com/benchmarks-list/)
- [How Inference Compute Shapes Frontier LLM Evaluation (arXiv 2606.17930)](https://arxiv.org/pdf/2606.17930)
- [SWE-bench Pro Leaderboard, Nov 2026 (Morph)](https://www.morphllm.com/swe-bench-pro)
- [SWE-Bench Pro Verified (arXiv 2609.08149)](https://arxiv.org/pdf/2609.08149)
- [DeepSWE (arXiv 2607.07946)](https://arxiv.org/pdf/2607.07946)
- [Vibe Code Bench (arXiv 2603.04601)](https://arxiv.org/pdf/2603.04601)
- [AI Agent Benchmarks 2026 (Codersera)](https://codersera.com/blog/ai-agent-benchmarks-state-of-leaderboard-may-2026/)
- [AI Agent Benchmarks: tau-bench, OSWorld, Terminal-bench](https://digitortoise.com/ai-agent-benchmarks-guide/)
- [BFCL v4 Leaderboard (BenchLM)](https://benchlm.ai/benchmarks/bfcl-v4)
- [Tool Calling Benchmarks: BFCL v4, tau-Bench (Spheron)](https://www.spheron.network/blog/tool-calling-benchmarks-bfcl-tau-bench-latency-optimization/)
- [AI Index Report 2026, Technical Performance (Stanford HAI)](https://hai.stanford.edu/assets/files/ai_index_report_2026_chapter_2_technical.pdf)
- [Humanity's Last Exam (Wikipedia)](https://en.wikipedia.org/wiki/Humanity%27s_Last_Exam)
- [HLE Diamond leaderboard (Village LLM Atlas)](https://atlas.village.dev/benchmarks/hle-diamond)
- [LLM Benchmarks Nov 2026 (BenchLeader)](https://www.benchleader.com/benchmarks)
- [MERA (mera.a-ai.ru)](https://mera.a-ai.ru/en)
- [Are You Getting What You Pay For? (arXiv 2504.04715)](https://arxiv.org/pdf/2504.04715)
- [Auditing Black-Box LLM APIs with a Rank-Based Uniformity Test (arXiv 2506.06975)](https://arxiv.org/pdf/2506.06975)
- [API-TAIL (arXiv 2610.36801)](https://arxiv.org/html/2610.36801)
- [Contagious Fingerprints (arXiv 2611.18104)](https://arxiv.org/html/2611.18104)
