"""
Упрощённый аналитический движок на основе доступных данных API-Football
"""
import logging
import math
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class MatchAnalytics:
    """Класс для анализа матча и расчета вероятностей"""

    def __init__(self, api):
        self.api = api

        # Кэш для турнирных таблиц и H2H (чтобы не делать повторные запросы)
        self.standings_cache = {}
        self.h2h_cache = {}

    async def analyze_match_70min(self, match_data: Dict, fixture_id: int) -> Optional[Dict]:
        """
        Полный анализ матча на 70-й минуте

        Args:
            match_data: Базовые данные матча
            fixture_id: ID матча

        Returns:
            Словарь с анализом или None
        """
        try:
            logger.info(f"🔍 Начинаем анализ матча {fixture_id}")

            # Получаем дополнительные данные
            statistics = await self.get_match_statistics(fixture_id)
            standings = await self.get_standings(match_data['league']['id'], match_data['league']['season'])
            h2h = await self.get_h2h(
                match_data['teams']['home']['id'],
                match_data['teams']['away']['id']
            )

            # Определяем проигрывающую команду
            home_goals = match_data['goals']['home'] or 0
            away_goals = match_data['goals']['away'] or 0

            if home_goals == away_goals:
                logger.info(f"⚖️ Ничья - анализ камбэка не требуется")
                return None

            losing_team = 'away' if home_goals > away_goals else 'home'
            winning_team = 'home' if home_goals > away_goals else 'away'

            score_diff = abs(home_goals - away_goals)

            logger.info(f"📊 Проигрывает: {losing_team.upper()}, разница: {score_diff}")

            # Расчет важности матча
            importance = self.calculate_match_importance(standings, match_data)

            # Расчет вероятности камбэка
            comeback_prob = self.calculate_comeback_probability(
                match_data, statistics, standings, h2h, losing_team, score_diff
            )

            # Прогноз голов
            goals_forecast = self.predict_remaining_goals(
                match_data, statistics, 70
            )

            # Определяем что на кону
            stakes = self.calculate_stakes(standings, match_data, importance)

            return {
                'importance': importance,
                'comeback_probability': comeback_prob,
                'goals_forecast': goals_forecast,
                'stakes': stakes,
                'losing_team': losing_team,
                'winning_team': winning_team,
                'score_diff': score_diff
            }

        except Exception as e:
            logger.error(f"❌ Ошибка анализа матча: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def get_match_statistics(self, fixture_id: int) -> Optional[Dict]:
        """Получает статистику матча"""
        try:
            data = await self.api._make_request('fixtures/statistics', {'fixture': fixture_id})

            if not data or not data.get('response'):
                logger.warning(f"⚠️ Нет статистики для матча {fixture_id}")
                return None

            # Преобразуем в удобный формат
            stats = {'home': {}, 'away': {}}

            for team_stats in data['response']:
                team_name = team_stats['team']['name']
                is_home = team_stats.get('statistics', [])

                team_key = 'home' if team_stats['team']['id'] == data['response'][0]['team']['id'] else 'away'

                for stat in team_stats.get('statistics', []):
                    stat_type = stat['type']
                    stat_value = stat['value']

                    # Преобразуем значения
                    if stat_value is None:
                        stat_value = 0
                    elif isinstance(stat_value, str):
                        if '%' in stat_value:
                            stat_value = int(stat_value.replace('%', ''))
                        else:
                            try:
                                stat_value = int(stat_value)
                            except:
                                stat_value = 0

                    # Сохраняем
                    if stat_type == 'Total Shots':
                        stats[team_key]['shots'] = stat_value
                    elif stat_type == 'Shots on Goal':
                        stats[team_key]['shots_on_goal'] = stat_value
                    elif stat_type == 'Ball Possession':
                        stats[team_key]['possession'] = stat_value
                    elif stat_type == 'Corner Kicks':
                        stats[team_key]['corners'] = stat_value
                    elif stat_type == 'Yellow Cards':
                        stats[team_key]['yellow_cards'] = stat_value
                    elif stat_type == 'Fouls':
                        stats[team_key]['fouls'] = stat_value

            return stats

        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики: {e}")
            return None

    async def get_standings(self, league_id: int, season: int) -> List[Dict]:
        """Получает турнирную таблицу (с кэшированием)"""
        cache_key = f"{league_id}_{season}_{datetime.now().strftime('%Y-%m-%d')}"

        if cache_key in self.standings_cache:
            logger.info(f"💾 Используем кэш турнирной таблицы")
            return self.standings_cache[cache_key]

        try:
            data = await self.api._make_request('standings', {
                'league': league_id,
                'season': season
            })

            if data and data.get('response') and len(data['response']) > 0:
                standings = data['response'][0]['league']['standings'][0]
                self.standings_cache[cache_key] = standings
                logger.info(f"✅ Получена турнирная таблица ({len(standings)} команд)")
                return standings

        except Exception as e:
            logger.error(f"❌ Ошибка получения таблицы: {e}")

        return []

    async def get_h2h(self, home_team_id: int, away_team_id: int) -> List[Dict]:
        """Получает историю личных встреч (с кэшированием)"""
        cache_key = f"{min(home_team_id, away_team_id)}_{max(home_team_id, away_team_id)}"

        if cache_key in self.h2h_cache:
            logger.info(f"💾 Используем кэш H2H")
            return self.h2h_cache[cache_key]

        try:
            data = await self.api._make_request('fixtures/headtohead', {
                'h2h': f"{home_team_id}-{away_team_id}",
                'last': 10
            })

            if data and data.get('response'):
                h2h = data['response']
                self.h2h_cache[cache_key] = h2h
                logger.info(f"✅ Получена история H2H ({len(h2h)} матчей)")
                return h2h

        except Exception as e:
            logger.error(f"❌ Ошибка получения H2H: {e}")

        return []

    def calculate_match_importance(self, standings: List[Dict], match_data: Dict) -> Dict:
        """
        Определяет важность матча на основе турнирной таблицы
        """
        try:
            if not standings:
                return {
                    'score': 50,
                    'category': 'Обычный',
                    'reason': 'Нет данных о таблице'
                }

            home_team_id = match_data['teams']['home']['id']
            away_team_id = match_data['teams']['away']['id']

            # Находим команды в таблице
            home_standing = next((t for t in standings if t['team']['id'] == home_team_id), None)
            away_standing = next((t for t in standings if t['team']['id'] == away_team_id), None)

            if not home_standing or not away_standing:
                return {
                    'score': 50,
                    'category': 'Обычный',
                    'reason': 'Команды не найдены в таблице'
                }

            home_pos = home_standing['rank']
            away_pos = away_standing['rank']
            home_points = home_standing['points']
            away_points = away_standing['points']

            total_teams = len(standings)
            matches_played = home_standing['all']['played']

            importance_score = 0
            category = 'Обычный'
            reason = ''

            # 1. КРИТИЧЕСКИ ВАЖНЫЙ: Борьба за чемпионство (топ-3)
            if home_pos <= 3 and away_pos <= 3:
                importance_score = 96
                category = 'Критически важный'
                reason = 'Борьба за чемпионство'

            # 2. ОЧЕНЬ ВАЖНЫЙ: Борьба за еврокубки (4-7 место)
            elif (4 <= home_pos <= 7) and (4 <= away_pos <= 7):
                points_diff = abs(home_points - away_points)
                if points_diff <= 3:
                    importance_score = 88
                    category = 'Очень важный'
                    reason = 'Прямая борьба за еврокубки'
                else:
                    importance_score = 72
                    category = 'Важный'
                    reason = 'Влияние на еврокубки'

            # 3. КРИТИЧЕСКИ ВАЖНЫЙ: Борьба за выживание
            elif home_pos >= (total_teams - 4) or away_pos >= (total_teams - 4):
                if home_pos >= (total_teams - 2) or away_pos >= (total_teams - 2):
                    importance_score = 95
                    category = 'Критически важный'
                    reason = 'Прямая угроза вылета'
                else:
                    importance_score = 82
                    category = 'Очень важный'
                    reason = 'Борьба за выживание'

            # 4. ДЕРБИ (бонус к важности)
            home_name = match_data['teams']['home']['name'].lower()
            away_name = match_data['teams']['away']['name'].lower()

            derby_cities = [
                'manchester', 'liverpool', 'london', 'madrid', 'barcelona',
                'milan', 'rome', 'munich', 'paris', 'istanbul'
            ]

            is_derby = any(
                city in home_name and city in away_name
                for city in derby_cities
            )

            if is_derby:
                importance_score = min(98, importance_score + 20)
                if category == 'Обычный':
                    category = 'Очень важный'
                reason = f"{'Принципиальное дерби' if not reason else reason + ' + дерби'}"

            # 5. Прямая борьба (команды рядом в таблице)
            if abs(home_pos - away_pos) <= 2 and abs(home_points - away_points) <= 6:
                importance_score = max(importance_score, 75)
                if category == 'Обычный':
                    category = 'Важный'
                    reason = 'Прямая борьба за место'

            # 6. Конец сезона (последние туры)
            total_matches = 38  # Стандарт для большинства лиг
            matches_remaining = total_matches - matches_played

            if matches_remaining <= 5 and importance_score >= 70:
                importance_score = min(100, importance_score + 10)
                category = 'Критически важный' if importance_score >= 90 else category
                reason += ' (решающая стадия)'

            # Если ничего особенного
            if importance_score == 0:
                importance_score = 45
                category = 'Обычный'
                reason = 'Матч середины таблицы'

            return {
                'score': min(100, max(0, importance_score)),
                'category': category,
                'reason': reason,
                'home_position': home_pos,
                'away_position': away_pos,
                'points_gap': abs(home_points - away_points)
            }

        except Exception as e:
            logger.error(f"❌ Ошибка расчета важности: {e}")
            return {
                'score': 50,
                'category': 'Обычный',
                'reason': 'Ошибка расчета'
            }

    def calculate_comeback_probability(self, match_data: Dict, statistics: Optional[Dict],
                                      standings: List[Dict], h2h: List[Dict],
                                      losing_team: str, score_diff: int) -> Dict:
        """
        Расчет вероятности камбэка
        """
        try:
            probability = 0.0
            factors = {}

            # Базовая вероятность в зависимости от разницы в счёте
            base_prob = {
                1: 0.35,  # -1 гол: 35% базовая
                2: 0.15,  # -2 гола: 15% базовая
                3: 0.05   # -3 гола: 5% базовая
            }
            probability = base_prob.get(score_diff, 0.02)

            # 1. ИГРОВАЯ СТАТИСТИКА (40% веса)
            if statistics:
                losing_stats = statistics.get(losing_team, {})
                winning_stats = statistics.get('home' if losing_team == 'away' else 'away', {})

                # 1a. Удары (15%)
                losing_shots = losing_stats.get('shots', 0)
                winning_shots = winning_stats.get('shots', 1)
                shots_ratio = losing_shots / max(1, winning_shots)

                if shots_ratio >= 1.5:
                    shots_score = 100
                elif shots_ratio >= 1.0:
                    shots_score = 70
                elif shots_ratio >= 0.7:
                    shots_score = 50
                else:
                    shots_score = 30

                probability += (shots_score / 100) * 0.15
                factors['Атакующая активность'] = f"{shots_score}%"

                # 1b. Удары в створ (15%)
                losing_sot = losing_stats.get('shots_on_goal', 0)
                winning_sot = winning_stats.get('shots_on_goal', 1)
                sot_ratio = losing_sot / max(1, winning_sot)

                if sot_ratio >= 1.5:
                    sot_score = 100
                elif sot_ratio >= 1.0:
                    sot_score = 75
                elif sot_ratio >= 0.7:
                    sot_score = 55
                else:
                    sot_score = 35

                probability += (sot_score / 100) * 0.15
                factors['Точность ударов'] = f"{sot_score}%"

                # 1c. Владение мячом (10%)
                losing_poss = losing_stats.get('possession', 50)

                if losing_poss >= 60:
                    poss_score = 85
                elif losing_poss >= 55:
                    poss_score = 70
                elif losing_poss >= 50:
                    poss_score = 55
                else:
                    poss_score = 35

                probability += (poss_score / 100) * 0.10
                factors['Контроль мяча'] = f"{poss_score}%"
            else:
                # Нет статистики - средние значения
                factors['Атакующая активность'] = "50%"
                factors['Точность ударов'] = "50%"
                factors['Контроль мяча'] = "50%"
                probability += 0.20  # 50% от 40%

            # 2. ФОРМА КОМАНД (20% веса)
            if standings:
                losing_team_id = match_data['teams'][losing_team]['id']
                losing_form = self.get_team_form(standings, losing_team_id)

                form_score = losing_form
                probability += (form_score / 100) * 0.20
                factors['Форма команды'] = f"{form_score}%"
            else:
                factors['Форма команды'] = "50%"
                probability += 0.10

            # 3. ДОМАШНЕЕ ПРЕИМУЩЕСТВО (15% веса)
            if losing_team == 'home':
                home_bonus = 68
                probability += 0.15 * (home_bonus / 100)
                factors['Домашнее поле'] = f"{home_bonus}%"
            else:
                factors['Домашнее поле'] = "0%"

            # 4. ИСТОРИЯ H2H (10% веса)
            if h2h:
                h2h_score = self.analyze_h2h_pattern(
                    h2h,
                    match_data['teams'][losing_team]['id']
                )
                probability += h2h_score * 0.10
                factors['История встреч'] = f"{int(h2h_score * 100)}%"
            else:
                factors['История встреч'] = "50%"
                probability += 0.05

            # 5. ТУРНИРНАЯ МОТИВАЦИЯ (15% веса)
            if standings:
                importance = self.calculate_match_importance(standings, match_data)
                motivation_score = importance['score']
                probability += (motivation_score / 100) * 0.15
                factors['Мотивация'] = f"{motivation_score}%"
            else:
                factors['Мотивация'] = "50%"
                probability += 0.075

            # Финальная вероятность
            final_probability = int(min(95, max(5, probability * 100)))

            # Определяем уровень уверенности
            if final_probability >= 70:
                confidence = 'Высокая'
                emoji = '🔥'
            elif final_probability >= 50:
                confidence = 'Средняя'
                emoji = '✅'
            else:
                confidence = 'Низкая'
                emoji = '⚠️'

            return {
                'probability': final_probability,
                'factors': factors,
                'confidence': confidence,
                'emoji': emoji
            }

        except Exception as e:
            logger.error(f"❌ Ошибка расчета камбэка: {e}")
            return {
                'probability': 50,
                'factors': {},
                'confidence': 'Низкая',
                'emoji': '⚠️'
            }

    def predict_remaining_goals(self, match_data: Dict, statistics: Optional[Dict],
                               current_minute: int) -> Dict:
        """
        Прогноз голов на оставшееся время (70' - 90'+)
        """
        try:
            time_remaining = 90 + 5 - current_minute  # +5 минут компенсированное время

            if not statistics:
                # Нет статистики - используем среднее
                return {
                    'home': 0.3,
                    'away': 0.3,
                    'total': 0.6,
                    'over_1_5_prob': 35
                }

            home_stats = statistics.get('home', {})
            away_stats = statistics.get('away', {})

            # Интенсивность атак
            home_shots = home_stats.get('shots', 0)
            away_shots = away_stats.get('shots', 0)
            total_shots = home_shots + away_shots

            if current_minute == 0:
                return {
                    'home': 0.3,
                    'away': 0.3,
                    'total': 0.6,
                    'over_1_5_prob': 35
                }

            # Удары за минуту
            shots_per_minute = total_shots / current_minute
            expected_shots_remaining = shots_per_minute * time_remaining

            # Конверсия удара в гол
            # В среднем 10-12% ударов становятся голами
            conversion_rate = 0.11

            # Учитываем, что на последних минутах команды атакуют активнее
            late_game_multiplier = 1.3

            # Распределение по командам
            home_ratio = home_shots / max(1, total_shots)
            away_ratio = 1 - home_ratio

            # Корректировка: проигрывающая команда атакует активнее
            home_goals = match_data['goals']['home'] or 0
            away_goals = match_data['goals']['away'] or 0

            if home_goals < away_goals:  # Home проигрывает
                home_ratio = min(0.75, home_ratio * 1.4)
                away_ratio = 1 - home_ratio
            elif away_goals < home_goals:  # Away проигрывает
                away_ratio = min(0.75, away_ratio * 1.4)
                home_ratio = 1 - away_ratio

            # Прогноз голов
            home_expected = expected_shots_remaining * home_ratio * conversion_rate * late_game_multiplier
            away_expected = expected_shots_remaining * away_ratio * conversion_rate * late_game_multiplier
            total_expected = home_expected + away_expected

            # Вероятность тотала > 1.5 (используем распределение Пуассона)
            def poisson_prob(k, lam):
                try:
                    return (lam ** k) * math.exp(-lam) / math.factorial(k)
                except:
                    return 0

            # P(X >= 2) = 1 - P(X=0) - P(X=1)
            p_0 = poisson_prob(0, total_expected)
            p_1 = poisson_prob(1, total_expected)
            over_1_5_prob = int((1 - p_0 - p_1) * 100)

            return {
                'home': round(home_expected, 1),
                'away': round(away_expected, 1),
                'total': round(total_expected, 1),
                'over_1_5_prob': max(5, min(95, over_1_5_prob))
            }

        except Exception as e:
            logger.error(f"❌ Ошибка прогноза голов: {e}")
            return {
                'home': 0.3,
                'away': 0.3,
                'total': 0.6,
                'over_1_5_prob': 35
            }

    def calculate_stakes(self, standings: List[Dict], match_data: Dict, importance: Dict) -> Dict:
        """
        Определяет что на кону в матче
        """
        try:
            if not standings:
                return {'summary': 'Нет данных о ставках'}

            home_id = match_data['teams']['home']['id']
            away_id = match_data['teams']['away']['id']

            home_standing = next((t for t in standings if t['team']['id'] == home_id), None)
            away_standing = next((t for t in standings if t['team']['id'] == away_id), None)

            if not home_standing or not away_standing:
                return {'summary': 'Команды не найдены в таблице'}

            home_pos = home_standing['rank']
            away_pos = away_standing['rank']
            home_points = home_standing['points']
            away_points = away_standing['points']

            total_teams = len(standings)

            stakes = {}

            # Победа хозяев
            home_win_pos = home_pos
            home_win_points = home_points + 3

            # Считаем новое место при победе
            teams_above = [t for t in standings if t['points'] > home_win_points or
                          (t['points'] == home_win_points and t['team']['id'] != home_id)]
            home_win_new_pos = len(teams_above) + 1

            if home_win_new_pos < home_pos:
                stakes['home_win'] = f"Подъём на {home_pos - home_win_new_pos} место(а)"
            elif home_pos <= 3:
                stakes['home_win'] = f"Отрыв +{home_win_points - away_points} очков от конкурента"
            else:
                stakes['home_win'] = f"+3 очка"

            # Победа гостей
            away_win_points = away_points + 3
            teams_above_away = [t for t in standings if t['points'] > away_win_points or
                               (t['points'] == away_win_points and t['team']['id'] != away_id)]
            away_win_new_pos = len(teams_above_away) + 1

            if away_win_new_pos < away_pos:
                stakes['away_win'] = f"Подъём на {away_pos - away_win_new_pos} место(а)"
            elif away_pos <= 3:
                stakes['away_win'] = f"Выход на {away_win_new_pos}-е место"
            else:
                stakes['away_win'] = f"+3 очка"

            # Ничья
            stakes['draw'] = "Сохранение позиций"

            return stakes

        except Exception as e:
            logger.error(f"❌ Ошибка расчета ставок: {e}")
            return {'summary': 'Ошибка расчета'}

    def get_team_form(self, standings: List[Dict], team_id: int) -> int:
        """
        Возвращает форму команды в процентах (0-100%)
        На основе последних 5 матчей
        """
        try:
            team = next((t for t in standings if t['team']['id'] == team_id), None)
            if not team:
                return 50

            form_str = team.get('form', '')
            if not form_str:
                return 50

            points = 0
            for result in form_str[-5:]:  # Последние 5
                if result == 'W':
                    points += 3
                elif result == 'D':
                    points += 1

            # Максимум 15 очков (5 побед)
            return int((points / 15) * 100)

        except:
            return 50

    def analyze_h2h_pattern(self, h2h: List[Dict], team_id: int) -> float:
        """
        Анализирует паттерн в личных встречах
        Возвращает score 0.0-1.0
        """
        if not h2h or len(h2h) == 0:
            return 0.5

        try:
            wins = 0
            draws = 0
            losses = 0

            for match in h2h[:5]:  # Последние 5 встреч
                winner_id = match.get('teams', {}).get('home', {}).get('winner')

                if winner_id is None:
                    draws += 1
                elif winner_id == team_id:
                    wins += 1
                else:
                    losses += 1

            total = wins + draws + losses
            if total == 0:
                return 0.5

            # Процент успеха (победа = 1, ничья = 0.5, поражение = 0)
            score = (wins + draws * 0.5) / total

            return score

        except:
            return 0.5