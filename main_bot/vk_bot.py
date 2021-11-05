""" Vkontakte bot module responsible for:
    - script of communication between the bot and the user,
    - formation of search queries,
    - sending search results for processing,
    - delivery of results to the user """

import os
import re
from datetime import datetime
from random import randrange
from typing import Dict, Any, Tuple, List

import vk_api
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.longpoll import VkLongPoll, VkEventType

from db.database import User, City, Status, Sex, Sort, Query, DatingUser, Country, Region, Connect
from main_bot.main_menu import VKUser, VKDatingUser, VKAuth


class Bot(VKAuth, Connect):
    def __init__(self):

        # укажите Ваш токен сообщества Вконтакте вместо os.getenv("VKINDER_TOKEN")
        TOKEN = os.getenv("VKINDER_TOKEN")
        self.vk_bot = vk_api.VkApi(token=TOKEN)
        self.longpoll = VkLongPoll(self.vk_bot)
        self.empty_keyboard = VkKeyboard().get_empty_keyboard()
        self.users = {}


    def _check_city_and_region(self, user) -> None:
        """A method for checking the presence of a city and a region in the database.
         If there is no data - collection and addition to the database"""

        if not self.select_from_db(City.id, City.id == user.city['id']).first():
            city, region = self._get_city(user.country['id'], user.city['title'])
            if not self.select_from_db(Region.id, Region.id == region['id']).first():
                self.insert_to_db(Region, region)
            self.insert_to_db(City, city)

    def _get_region(self, country_id: int, region_title: str) -> Dict[str, Any]:

        """ Method for searching the user's region if the data is not in the database """

        search_values = {'country_id': country_id, 'q': region_title}
        return self.vk_session.method('database.getRegions', values=search_values)

    def _get_city(self, country_id, city_title):

        """ Method for finding the user's city, if the data is not in the database """

        search_values = {'country_id': country_id, 'q': city_title, 'need_all': 1}
        city = self.vk_session.method('database.getCities', values=search_values)
        city_items = city['items']
        if city_items:
            city_items = city_items[0]
            region_title = city_items.get('region')
            if region_title:
                region_title = region_title.split()[0]
                region = self._get_region(country_id, region_title)
                region_items = region['items'][0]
                region_items.update({'country_id': country_id})
                city_items['region_id'] = region_items['id']
                return city_items, region_items
            return city_items, None
        return None, None


    def write_msg(self, user_id, message, attachment=None, keyboard=None):

        """Sending a message to the user"""

        values = {'user_id': user_id, 'message': message, 'random_id': randrange(10 ** 7)}
        if attachment:
            values['attachment'] = attachment
        if keyboard:
            values['keyboard'] = keyboard

        self.vk_bot.method('messages.send', values)

    def listen_msg(self, scan=True):

        """Waiting for messages from the user and processing them.
        The method monitors events in VKLongPoll
        and at the first event from the user initializes its VKUser instance """

        def scan_request(event):

            request = event.text.lower().strip()
            query = re.findall(r'([А-Яа-яЁёA-Za-z0-9]+)', request)
            if len(query) > 1:
                query = ' '.join(query)
            else:
                try:
                    query = query[0]
                except IndexError:
                    query = request
            return query

        for event in self.longpoll.listen():
            try:
                user = self.users.get(event.user_id)
                if not user:
                    user = self.create_user(event.user_id)

                if not user.welcomed:
                    self.welcome_user(user)

                if event.type == VkEventType.MESSAGE_NEW:
                    if event.to_me:
                        if scan is True:
                            return scan_request(event), user
                        return event.text, user
            except AttributeError:
                pass

    def create_user(self, id):
        self.users[id] = VKUser(id)
        user = self.users[id]
        return user

    def check_user_city(self, user):

        self._check_city_and_region(user)

        # we check if the user wants to change the city
        user_db_city = self.select_from_db(User.city_id, User.id == user.user_id).first()
        if user_db_city:
            user_db_city = user_db_city[0]
        if user_db_city != user.city['id']:
            self.update_data(User.id, User.id == user.user_id, {User.city_id: user.city['id']})
            user_db_city = self.select_from_db(User.city_id, User.id == user.user_id).first()[0]

        return user_db_city

    def insert_query(self, user_id, search_values):

        """ The method of recording information about the user's search conditions in the database"""

        fields = {
            'datetime': datetime.utcnow(),
            'sex_id': search_values['sex'],
            'city_id': search_values['city'],
            'age_from': search_values['age_from'],
            'age_to': search_values['age_to'],
            'status_id': search_values['status'],
            'sort_id': search_values['sort'],
            'user_id': user_id
        }
        self.insert_to_db(Query, fields)

        return self.select_from_db(Query.id, Query.id == Query.id).order_by(Query.datetime.desc()).first()[0]

    def search_users(self, vk_user, values: Dict[str, Any] = None):

        search_values = {
            'city': 1,
            'sex': 1,
            'age_from': 20,
            'age_to': 45,
            'status': 6,
            'sort': 1,
            'count': 1000,
            'has_photo': 3,
            'is_closed': 0,
            'can_access_closed': 1,
            'fields': 'id, verified, domain'
        }

        if values:
            search_values.update(values)

        users_list = self.vk_session.method('users.search', values=search_values)['items']

        if not users_list:
            return
        query_id = self.insert_query(vk_user.user_id, search_values)
        d_users = 0
        for user in users_list:
            if user['is_closed'] == 1:
                continue

            user['vk_id'] = user.pop('id')
            user['city_id'] = search_values['city']
            user['city_title'] = self.select_from_db(City.title, City.id == search_values['city']).first()[0]
            user['link'] = 'https://vk.com/' + user.pop('domain')
            user['verified'] = user.get('verified')
            user['query_id'] = query_id
            user['viewed'] = False

            user.pop('is_closed')
            user.pop('can_access_closed')
            user.pop('track_code')

            shown_user = self.select_from_db(DatingUser.viewed, (DatingUser.vk_id == user['vk_id'],
                                                                 DatingUser.query_id == query_id)).first()
            if shown_user:
                if shown_user[0] is True:
                    continue
                elif shown_user[0] is False:
                    last_query = self.select_from_db(Query.id,
                                                     Query.user_id == user.user_id).order_by(
                        Query.datetime.desc()).first()[0]

                    self.update_data(DatingUser.id,
                                     expression=(DatingUser.vk_id == user['vk_id'],
                                                 DatingUser.query_id == last_query,
                                                 DatingUser.viewed.is_(False)),
                                     fields={DatingUser.query_id: query_id})
                    d_users += 1
            else:
                self.insert_to_db(DatingUser, user)
                d_users += 1

        return d_users, query_id

    def show_results(self, user, results: Tuple[int, int] = None, datingusers: List[VKDatingUser] = None):

        if datingusers:
            dating_users = datingusers
        else:
            if results:
                remainder = results[0] % 10
                if remainder == 0 or remainder >= 5 or (10 <= results[0] <= 19) or (10 <= results[0] % 100 <= 19):
                    var = 'вариантов'
                elif remainder == 1:
                    var = 'вариант'
                else:
                    var = 'варианта'
                self.write_msg(user.user_id, f'&#129395;Мы нашли {results[0]} {var}!!! &#129395;')
                query_id = results[1]
                dating_users = self.get_datingusers_from_db(user.user_id, query_id)
            else:
                dating_users = self.get_datingusers_from_db(user.user_id)

        if dating_users:
            # get a list of users from the database
            for d_user in dating_users:
                d_user.photos = d_user.get_photo()
                name = d_user.first_name + ' ' + d_user.last_name
                link = d_user.link
                if len(d_user.photos) > 1:
                    photos_list = []
                    for photo in d_user.photos:
                        photo_id, owner_id = photo
                        photos_list.append(f'Фотография {owner_id}_{photo_id}')
                    photos = ','.join(photos_list)
                    message = f'{name} {link} \n '
                elif len(d_user.photos) == 1:
                    photo_id, owner_id = d_user.photos[0]
                    photos = f'photo{owner_id}_{photo_id}'
                    message = f'{name} {link} \n '
                else:
                    message = f'{name} {link} \n Фотографий нет.\n'
                    photos = ''

                keyboard = VkKeyboard(one_time=False)
                keyboard.add_button("Да", color=VkKeyboardColor.POSITIVE)
                keyboard.add_button("Нет", color=VkKeyboardColor.NEGATIVE)
                keyboard.add_line()
                keyboard.add_button("Отмена", color=VkKeyboardColor.SECONDARY)
                keyboard = keyboard.get_keyboard()
                if photos:
                    self.write_msg(user.user_id, message=message, attachment=photos)
                else:
                    self.write_msg(user.user_id, message=message)
                self.write_msg(user.user_id, message='Нравится?', keyboard=keyboard)

                expected_answers = ['да', 'нет', 'отмена']
                answer = self.listen_msg()[0]
                while answer not in expected_answers:
                    self.write_msg(user.user_id, "&#128280; Попробуй использовать кнопки! &#128280;",
                                   keyboard=keyboard)
                    answer = self.listen_msg()[0]
                else:
                    if answer == "да":
                        fields = {DatingUser.viewed: True, DatingUser.black_list: False}
                        self.update_data(DatingUser.id, DatingUser.id == d_user.db_id, fields=fields)
                        return 'Пришло время для новых знакомств!'
                    elif answer == "нет":
                        fields = {DatingUser.viewed: True, DatingUser.black_list: True}
                        self.update_data(DatingUser.id, DatingUser.id == d_user.db_id, fields=fields)
                        return 'обнови страницу и попробуй заного'
                    elif answer == "отмена":
                        self.write_msg(user.user_id, "Попробуем еще?  &#128540;",
                                       keyboard=self.empty_keyboard)
                        return
        self.write_msg(user.user_id, "&#128564; Поиск завершен. Начать новый поиск?  &#128540;",
                       keyboard=self.empty_keyboard)
        return

    def get_datingusers_from_db(self, user_id, query_id=None, blacklist=None):

        fields = (
            DatingUser.id,
            DatingUser.vk_id,
            DatingUser.first_name,
            DatingUser.last_name,
            DatingUser.link,
        )

        if query_id:
            vk_users = self.select_from_db(fields, (DatingUser.query_id == query_id,
                                                    DatingUser.viewed.is_(False))).all()
        else:
            if blacklist is None:
                query_id = self.select_from_db(Query.id,
                                               Query.user_id == user_id).order_by(Query.datetime.desc()).first()[0]
                vk_users = self.select_from_db(fields, (DatingUser.query_id == query_id,
                                                        DatingUser.viewed.is_(False))).all()

            elif blacklist is False:
                vk_users = self.select_from_db(model_fields=fields,
                                               join=Query,
                                               expression=(Query.user_id == user_id, DatingUser.black_list.is_(False)))

            else:
                vk_users = self.select_from_db(model_fields=fields,
                                               join=Query,
                                               expression=(Query.user_id == user_id, DatingUser.black_list.is_(True)))
        if vk_users:
            dating_users = [VKDatingUser(user[0], user[1], user[2], user[3], user[4]) for user in vk_users]
            return dating_users
        return

                #dialogue methods

    def welcome_user(self, user):

        keyboard = VkKeyboard(one_time=False)
        user_in_db = user.select_from_db(User.id, User.id == user.user_id).first()

        if not user_in_db:
            user.insert_self_to_db()

            keyboard.add_button("Привет", color=VkKeyboardColor.SECONDARY)
            keyboard.add_button("Новый поиск", color=VkKeyboardColor.POSITIVE)

            self.write_msg(user.user_id, f"&#9995;  Привет, {user.first_name.capitalize()}! &#128515;",
                           keyboard=keyboard.get_keyboard())

        else:
            check_query = user.select_from_db(Query.id, Query.user_id == user.user_id).all()
            if not check_query:

                keyboard.add_button("Привет", color=VkKeyboardColor.SECONDARY)
                keyboard.add_button("Новый поиск", color=VkKeyboardColor.POSITIVE)

                self.write_msg(user.user_id,
                               f"&#128522; Привет, {user.first_name.capitalize()}! Попробуем поискать кого-нибудь?",
                               keyboard=keyboard.get_keyboard())
            else:
                keyboard.add_button("Привет", color=VkKeyboardColor.SECONDARY)
                keyboard.add_button("Новый поиск", color=VkKeyboardColor.POSITIVE)
                keyboard.add_line()
                keyboard.add_button(f"Результаты последнего поиска", color=VkKeyboardColor.SECONDARY)
                keyboard.add_line()
                keyboard.add_button(f"Все, кто понравился", color=VkKeyboardColor.POSITIVE)
                keyboard.add_button(f"кто не понравился", color=VkKeyboardColor.NEGATIVE)
                self.write_msg(user.user_id,
                               f"&#128522; Привет, {user.first_name.capitalize()}! Попробуем поискать кого-нибудь?",
                               keyboard=keyboard.get_keyboard())
        user.welcomed = True
        return user.welcomed

    def get_sex(self, user):

        sex = [name[0] for name in user.select_from_db(Sex.title, Sex.id == Sex.id).all()]
        sex.append("Отмена")

        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button(sex[1].capitalize(), VkKeyboardColor.NEGATIVE)
        keyboard.add_button(sex[2].capitalize(), VkKeyboardColor.PRIMARY)
        keyboard.add_line()
        keyboard.add_button(sex[0].capitalize(), VkKeyboardColor.SECONDARY)
        keyboard.add_button('Отмена', VkKeyboardColor.NEGATIVE)
        keyboard = keyboard.get_keyboard()

        self.write_msg(user.user_id, f'Людей какого пола мы будем искать?', keyboard=keyboard)

        answer = self.listen_msg()[0].strip().lower()

        while answer not in sex:
            self.write_msg(user.user_id, '&#129300; Извините, я не разобрал. Выберите ответ повторно. &#128071;')
            answer = self.listen_msg()[0].strip().lower()
        else:
            if answer == "отмена":
                return
            return sex.index(answer)

    def get_city(self, user):

        self.write_msg(user.user_id, f'В каком городе будем искать?\n\nНазвания зарубежных городов, таких как Лондон '
                                     f'или Париж, должны быть написаны латинницей и полностью.\n\nНа всякий случай: '
                                     f'самый Нью-Йорк следует написать так: '
                                     f'New York City.',
                       keyboard=cancel_button())
        while True:
            answer = self.listen_msg(scan=False)[0].strip().lower()
            if answer == "отмена":
                return
            try:
                symbol = re.search(r'\W', answer)[0]
                words = re.split(symbol, answer)
                if len(words) < 3:
                    for word in words:
                        words[words.index(word)] = word.capitalize()
                    answer = symbol.join(words)
                else:
                    if '-' == symbol:
                        words[0] = words[0].capitalize()
                        words[-1] = words[-1].capitalize()
                        answer = symbol.join(words)
                    else:
                        answer = answer.title()
            except TypeError:
                answer = answer.capitalize()

            city = user.select_from_db(City, City.title.startswith(answer)).order_by(City.region).all()

            if not city:
                self.write_msg(user.user_id, f'&#128530; Я не знаю такого города... '
                                             f'Выбери другой или попробуй написать иначе. '
                                             f'Не забывай про пробелы и дефисы')
            else:
                break

        if len(city) == 1:
            return city[0].id
        elif len(city) > 1:
            self.write_msg(user.user_id, f'Нужно уточнить, какой город ты имеешь в виду:')
            ids = [(city.id, city.title) for city in city]
            ids.sort(key=lambda x: x[0])
            cities = {}

            message_list = []
            message = ''

            for num, (id, title) in enumerate(ids, start=1):
                cities[str(num)] = id

                try:
                    region_name, region_id, area = user.select_from_db((City.region, City.region_id, City.area),
                                                                       City.id == id).first()

                    country = user.select_from_db(Country.title, Region.id == region_id,
                                                  join=(Region, Country.id == Region.country_id)).first()[0]
                except TypeError:
                    area = None
                    region_name = 'Нет информации'
                    country = 'Нет информации'

                if area:
                    string = f'{num} - {title}, {region_name}, {area} ({country})\n'
                else:
                    string = f'{num} - {title}, {region_name} ({country})\n'

                if len(message + string) > 4097:  # maximum length of a VK message
                    message_list.append(message)
                    message = ''
                message += string
            message_list.append(message)
            for message in message_list:
                self.write_msg(user.user_id, message)

            expected_answers = [str(i) for i in range(1, len(city) + 1)]
            answer = self.listen_msg()[0].strip()
            expected_answers.append('отмена')
            while answer not in expected_answers:
                self.write_msg(user.user_id, f'Мне нужен один из порядковых номеров, которые ты видишь чуть выше.')
                answer = self.listen_msg()[0].strip()
            else:
                if answer == "отмена":
                    return
                return cities[answer]

    def get_age_from(self, user):

        self.write_msg(user.user_id, f'Укажи минимальный возраст в цифрах.', keyboard=cancel_button())
        while True:
            answer = self.listen_msg()[0].strip().lower()
            try:
                answer = int(answer)
            except ValueError:
                if answer == "отмена":
                    return
                else:
                    self.write_msg(user.user_id, f'Укажи минимальный возраст в цифрах!')
            return abs(answer)

    def get_age_to(self, user):

        self.write_msg(user.user_id, f'Укажи максимальный возраст в цифрах или отправь 0, если это неважно.',
                       keyboard=cancel_button())
        while True:
            answer = self.listen_msg()[0].strip().lower()
            try:
                answer = int(answer)
            except ValueError:
                if answer == "отмена":
                    return
                else:
                    self.write_msg(user.user_id,
                                   f'Укажи максимальный возраст в цифрах или отправь 0, если это неважно.')
            else:
                if answer != 0:
                    return abs(answer)
                return 100

    def get_status(self, user):

        statuses = [name[0] for name in user.select_from_db(Status.title, Status.id == Status.id).all()]
        statuses.append("Отмена")

        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button(statuses[0], VkKeyboardColor.POSITIVE)
        keyboard.add_button(statuses[1], VkKeyboardColor.PRIMARY)
        keyboard.add_line()
        keyboard.add_button(statuses[2], VkKeyboardColor.SECONDARY)
        keyboard.add_button(statuses[3], VkKeyboardColor.NEGATIVE)
        keyboard.add_line()
        keyboard.add_button(statuses[5], VkKeyboardColor.POSITIVE)
        keyboard.add_button(statuses[4], VkKeyboardColor.PRIMARY)
        keyboard.add_line()
        keyboard.add_button(statuses[6], VkKeyboardColor.SECONDARY)
        keyboard.add_button(statuses[7], VkKeyboardColor.NEGATIVE)
        keyboard.add_line()
        keyboard.add_button("Отмена", VkKeyboardColor.NEGATIVE)
        keyboard = keyboard.get_keyboard()

        self.write_msg(user.user_id, f'Какой из статусов тебя интересует?', keyboard=keyboard)

        answer = self.listen_msg(scan=False)[0].strip()

        while answer not in statuses:
            self.write_msg(user.user_id, '&#129300; Попробуй еще раз ... &#128071;')
            answer = self.listen_msg()[0].strip()
        else:
            if answer == "Отмена":
                return
            return statuses.index(answer) + 1

    def get_sort(self, user):

        sort_names = [name[0] for name in user.select_from_db(Sort.title, Sort.id == Sort.id).all()]
        sort_names.append("отмена")
        keyboard = VkKeyboard(one_time=False)
        keyboard.add_button(sort_names[0], VkKeyboardColor.POSITIVE)
        keyboard.add_button(sort_names[1], VkKeyboardColor.PRIMARY)
        keyboard.add_line()
        keyboard.add_button("Отмена", VkKeyboardColor.NEGATIVE)
        keyboard = keyboard.get_keyboard()
        self.write_msg(user.user_id, f'Как отсортировать пользователей?', keyboard=keyboard)

        answer = self.listen_msg()[0].strip()
        while answer not in sort_names:
            self.write_msg(user.user_id, '&#129300; Я не понимаю... Используй кнопки! &#128071;')
            answer = self.listen_msg()[0].strip()
        else:
            if answer == "отмена":
                return
            return sort_names.index(answer)

    def questionnaire(self, user, values=None, full=False) -> Dict[str, Any] or int:

        search_values = {
            'sex': None,
            'city': None,
            'age_from': None,
            'age_to': None,
            'status': None,
            'sort': None,
        }

        if values:
            search_values.update(values)

        if full:
            sex = self.get_sex(user)
            if sex is None:
                return
        else:
            sex = search_values['sex']

        city = self.get_city(user)
        if city is None:
            return

        age_from = self.get_age_from(user)
        if age_from is None:
            return

        age_to = self.get_age_to(user)
        if age_to is None:
            return

        status = self.get_status(user)
        if status is None:
            return

        sort = self.get_sort(user)
        if sort is None:
            return

        search_values['sex'] = sex
        search_values['city'] = city
        search_values['age_from'] = age_from
        search_values['age_to'] = age_to
        search_values['status'] = status
        search_values['sort'] = sort

        return search_values

    def initial_questionnaire(self, user, search_values) -> Tuple[int, int] or int:

        expected_answers = ['да', 'нет']
        answer = self.listen_msg()[0].strip()
        while answer not in expected_answers:
            self.write_msg(user.user_id, '&#129300; Я не понимаю... Просто скажи "да" или "нет" '
                                         'или используй кнопки! &#128071;')
            answer = self.listen_msg()[0].strip()
        else:
            if answer == 'да':

                keyboard = VkKeyboard(one_time=False)
                keyboard.add_button("обычный", VkKeyboardColor.PRIMARY)
                keyboard.add_button("подробный", VkKeyboardColor.SECONDARY)
                keyboard.add_line()
                keyboard.add_button("отмена", VkKeyboardColor.NEGATIVE)
                keyboard = keyboard.get_keyboard()
                self.write_msg(user.user_id, f"Какой вид поиска будем использовать? &#128071;", keyboard=keyboard)

                expected_answers = ["обычный", "подробный", "отмена"]
                answer = self.listen_msg()[0].strip()
                while answer not in expected_answers:
                    self.write_msg(user.user_id, '&#128280; Не понимаю... Используй кнопки. &#128280;')
                    answer = self.listen_msg()[0].strip()
                else:
                    if answer == "обычный":
                        self.write_msg(user.user_id, f"&#128150; Прекрасный выбор! &#128150;")
                        return search_values
                    elif answer == "подробный":
                        self.write_msg(user.user_id,
                                       f"&#128076; Хорошо! Тебе нужно будет ответить на несколько вопросов.")
                        return self.questionnaire(user, search_values)
                    else:
                        return
            elif answer == 'нет':
                return self.questionnaire(user, full=True)

    def start(self):
        """The main_bot method of the bot operation, which is responsible for the program
         of the user's dialogue with the bot."""

        answer, user = self.listen_msg()

        search_values = {
            'city': user.city['id'],
            'sex': None,
            'age_from': 18,
            'age_to': 100,
            'status': 6,
            'sort': 0,
        }

        expected_answers = ['привет', 'новый поиск', "результаты последнего поиска",
                            "все, кто понравился", "все, кто не понравился"]
        while answer not in expected_answers:
            self.write_msg(user.user_id, "&#128280; Не понимаю... Используй кнопки. &#128280;")
            answer = self.listen_msg()[0]
        else:
            if answer == "привет":
                keyboard = VkKeyboard(one_time=False)
                keyboard.add_button("Да", VkKeyboardColor.POSITIVE)
                keyboard.add_button("Нет", VkKeyboardColor.NEGATIVE)

                if user.sex == 2:
                    search_values['sex'] = 1
                    self.write_msg(user.user_id, f"Ищем девушку?", keyboard=keyboard.get_keyboard())
                    search_values = self.initial_questionnaire(user, search_values)

                elif user.sex == 1:
                    search_values['sex'] = 2
                    self.write_msg(user.user_id, f"Ищем парня?", keyboard=keyboard.get_keyboard())
                    search_values = self.initial_questionnaire(user, search_values)

                else:
                    search_values = self.questionnaire(user, full=True)

                if search_values:
                    return user, search_values
                return user, None

            elif answer == "новый поиск":
                search_values = self.questionnaire(user, full=True)
                if search_values:
                    return user, search_values
                return user, None

            elif answer == "результаты последнего поиска":
                last_user_query = self.get_datingusers_from_db(user.user_id)
                if last_user_query:
                    return user, last_user_query
                return user

            elif answer == "все, кто понравился":
                liked_users = self.get_datingusers_from_db(user.user_id, blacklist=False)
                if liked_users:
                    message_list = []
                    message = ''
                    for num, d_user in enumerate(liked_users, start=1):
                        if len(message + f'{num}. {d_user}\n') > 4097:
                            message_list.append(message)
                            message = ''
                        message += f'{num}. {d_user}\n'
                    message_list.append(message)
                    for message in message_list:
                        self.write_msg(user.user_id, message)
                    return user, liked_users
                return user

            elif answer == "все, кто не понравился":
                blacklist = self.get_datingusers_from_db(user.user_id, blacklist=True)
                if blacklist:
                    message_list = []
                    message = ''
                    for num, d_user in enumerate(blacklist, start=1):
                        if len(message + f'{num}. {d_user}\n') > 4097:
                            message_list.append(message)
                            message = ''
                        message += f'{num}. {d_user}\n'
                    message_list.append(message)
                    for message in message_list:
                        self.write_msg(user.user_id, message)
                    return user, blacklist
                return user


def cancel_button() -> VkKeyboard:

    """Emergency exit button from the dialogue with the bot"""

    keyboard = VkKeyboard(one_time=False)
    keyboard.add_button("Отмена", color=VkKeyboardColor.NEGATIVE)
    return keyboard.get_keyboard()


def main():
    bot = Bot()
    while True:
        start = bot.start()
        if isinstance(start, VKUser):
            user = start
            bot.write_msg(user.user_id, "&#128579; Поиск завершен. Начать новый? &#128373;",
                          keyboard=bot.empty_keyboard)
        else:
            user, values = start
            if isinstance(values, dict):
                results = bot.search_users(user, values)
                if not results:
                    bot.write_msg(user.user_id,
                                  f'&#128530; Похоже, что в этом городе нет никого, кто отвечал бы таким '
                                  f'условиям поиска.\nПопробуй использовать подробный поиск или '
                                  f'изменить условия запроса.', keyboard=bot.empty_keyboard)
                else:
                    bot.show_results(user, results=results)

            elif isinstance(values, list):
                bot.show_results(user, datingusers=values)
            elif not values:
                bot.write_msg(user.user_id,
                              f'&#128521; Ок, начнём сначала!', keyboard=bot.empty_keyboard)

        user.welcomed = False


if __name__ == '__main__':
    main()