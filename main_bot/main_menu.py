'''Vkontakte entity module responsible for:
    - authorization of the program as a VK user,
    - creating instances of VK user entities in a dialogue with the bot,
    - creating instances of VK users' entities obtained as a result of a search
    - processing of search results.
    Additionally, the module has a separate class "VKGeoData" for collecting information about any toponyms from the VK database
    for its subsequent recording into the program's own database.'''

import os
import vk_api
import json
import operator
from typing import List, Dict, Any
from ratelimit import limits
from tqdm import tqdm
from db.database import Connect, User
from datetime import datetime


LIST_OF_DICTS = List[Dict[str, Any]]


class VKAuth:

    TOKEN = os.getenv("VK_USER_TOKEN")

    if TOKEN:
        vk_session = vk_api.VkApi(token=TOKEN)
    else:
        username = os.getenv("VK_USER_LOGIN")
        password = os.getenv("VK_USER_PASS")
        scope = 'users,notify,friends,photos,status,notifications,offline,wall,audio,video'
        if not username or not password:
            username: str = input('Введите свой логин: ')
            password: str = input('Введите свой пароль: ')
        vk_session = vk_api.VkApi(username, password, scope=scope)

    try:
        vk_session.auth(token_only=True)
    except vk_api.AuthError as error_message:
        print(error_message)


class VKUser(VKAuth, Connect):

    """A class for collecting information about a user for further selection of a suitable person"""

    def __init__(self, id: int):
        self.user_id = id
        info = self.get_self_info(self.user_id)
        self.first_name = info[0].get('first_name')
        self.last_name = info[0].get('last_name')
        self.sex = info[0].get('sex')
        self.link = 'https://vk.com/' + str(info[0].get('domain'))
        self.welcomed = False

        # If the city and country of the user are not specified - Moscow by default
        if not info[0].get('city'):
            self.city = {'id': 1, 'title': 'Москва'}
            self.country = {'id': 1, 'title': 'Россия'}
        else:
            self.city = info[0].get('city')
            self.country = info[0].get('country')

    def get_self_info(self, user_id: int):

        """ Method to get all information about a user """

        search_values = {
            'user_id': user_id,
            'fields': 'city, country, sex, domain, home_town'
        }
        return self.vk_session.method('users.get', values=search_values)

    def insert_self_to_db(self) -> None:

        fields = {
            'id': self.user_id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'sex_id': self.sex,
            'city_id': self.city['id'],
            'link': self.link
        }

        if not self.select_from_db(User.id, User.id == self.user_id).first():
            self.insert_to_db(User, fields)


class VKDatingUser(VKAuth):

    """This class is responsible for the selection of a person at the user's request
    and produces three of his popular photos"""

    def __init__(self, db_id: int, vk_id: int, first_name: str, last_name: str, vk_link: str):
        self.db_id = db_id
        self.id = vk_id
        self.first_name = first_name
        self.last_name = last_name
        self.link = vk_link

    def __str__(self):
        return f'Тебе нравится {self.first_name} {self.last_name}? Вот ссылка на страницу - {self.link}'

    def get_photo(self):

        search_values = {'owner_id': self.id,
                         'album_id': 'profile',
                         'count': 1000,
                         'extended': 1,
                         'photo_sizes': 1,
                         'type': 'm'}

        response = self.vk_session.method('photos.get', values=search_values)
        photos = []

        for photo in response['items']:
            photos.append((photo['id'], photo['owner_id'], photo['likes']['count']))

        sorted_photos = sorted(photos, key=operator.itemgetter(2), reverse=True)
        top_photos = [(id, photo) for id, photo, _ in sorted_photos][:3]
        return top_photos

class VKGeoData(VKAuth):
    """ Class with utility methods for collecting information for the database """

    REQUESTS_PER = 3
    SECOND = 1

    def get_countries(self) -> LIST_OF_DICTS:
        """ Service method for collecting all countries.
        Used to fill the database """

        print('Страны')
        countries = []
        countries_query = self.vk_session.method('database.getCountries',
                                                 values={'need_all': 1, 'count': 1000})['items']

        for country in countries_query:
            new_dic = {'model': 'country', 'fields': country}
            countries.append(new_dic)

        with open('../db/fix/countries.json', 'w', encoding='utf-8') as f:
            json.dump(countries, f)
        return countries_query

    @limits(REQUESTS_PER, SECOND)
    def get_regions(self, countries: LIST_OF_DICTS = None) -> LIST_OF_DICTS:

        print('Регионы')
        regions = [{'model': 'region', 'fields': {"id": 1, "title": "Москва город", "country_id": 1}},
                   {'model': 'region', 'fields': {"id": 2, "title": "Санкт-Петербург город", "country_id": 1}}]

        if not countries:
            try:
                with open('../db/fix/countries.json', 'r', encoding='utf-8') as f:
                    countries = json.load(f)
            except (FileNotFoundError, FileExistsError):
                countries = self.get_countries()

        for country in countries:
            print(".", end='')

            regions_quantity = self.vk_session.method('database.getRegions', values={'country_id': country['fields']['id'],
                                                                                        'count': 100})['count']
            if regions_quantity:
                search_values = {'country_id': country['fields']['id'], 'count': 100}
                regions_quantity = self.vk_session.method('database.getRegions', values=search_values)['count']
                if regions_quantity > 100:
                    queries = regions_quantity // 100 + 1
                    values = {'country_id': country['fields']['id'],
                              'count': 100,
                              'offset': 0}
                    for query in tqdm(range(queries), desc=f"Обход регионов в стране {country['fields']['title']}"):
                        values['offset'] = 100 * query
                        regions_list = self.vk_session.method('database.getRegions', values=values)['items']
                        if regions_list:
                            for region in regions_list:
                                region.update({'country_id': country['fields']['id']})
                                new_dict = {'model': 'region', 'fields': region}
                                regions.append(new_dict)

                else:
                    regions_list = self.vk_session.method('database.getRegions', values=search_values)['items']
                    if regions_list:
                        for region in regions_list:
                            region.update({'country_id': country['fields']['id']})
                            new_dict = {'model': 'region', 'fields': region}
                            regions.append(new_dict)

        with open('../db/fix/regions.json', 'w', encoding='utf-8') as f:
            json.dump(regions, f)
        return regions

    @limits(REQUESTS_PER, SECOND)
    def get_cities(self, regions: LIST_OF_DICTS = None) -> LIST_OF_DICTS:

        """ A service method for collecting all cities in all countries.
        Used to fill the database """

        print('Загрузка названий городов')
        cities = []

        if not regions:
            try:
                with open('../db/fix/regions.json', 'r', encoding='utf-8') as f:
                    regions = json.load(f)
            except (FileNotFoundError, FileExistsError):
                regions = self.get_regions()

        for region in regions:
            print(".", end='')

            search_values = {'country_id': region['fields']['country_id'],
                             'region_id': region['fields']['id'],
                             'need_all': 1,
                             'count ': 100}
            cities_quantity = self.vk_session.method('database.getCities', values=search_values)['count']

            if cities_quantity:
                if cities_quantity > 100:
                    queries = cities_quantity // 100 + 1
                    values = {'country_id': region['fields']['country_id'],
                              'region_id': region['fields']['id'],
                              'offset': 0,
                              'need_all': 1,
                              'count ': 100}
                    for query in tqdm(range(queries), desc=f"Обход всех городов в регионе {region['fields']['title']}"):

                        values['offset'] = 100 * query
                        cities_list = self.vk_session.method('database.getCities', values=values)['items']
                        if cities_list:
                            for city in cities_list:
                                city.update({'region_id': region['fields']['id']})
                                new_dic = {'model': 'city', 'fields': city}
                                cities.append(new_dic)

                else:
                    cities_list = self.vk_session.method('database.getCities', values=search_values)['items']
                    if cities_list:
                        for city in cities_list:
                            city.update({'region_id': region['fields']['id']})
                            new_dic = {'model': 'city', 'fields': city}
                            cities.append(new_dic)

        with open('../db/fix/cities.json', 'w', encoding='utf-8') as f:
            json.dump(cities, f)
        return cities



if __name__ == '__main__':
    geo = VKGeoData()
    now = datetime.now()
    print(now)
    geo.get_countries()
    geo.get_regions()
    geo.get_cities()
    print(datetime.now() - now)