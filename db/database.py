import itertools
import json
from datetime import datetime
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, create_engine, inspect
from tqdm import tqdm

base = declarative_base()


def grouper(iterable, i, fillvalue=None):

    """Collect data into fixed-length chunks or blocks"""
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"
    # https://docs.python.org/3/library/itertools.html#itertools-recipes

    args = [iter(iterable)] * i
    return itertools.zip_longest(*args, fillvalue=fillvalue)


class Connect:

    engine = create_engine(f'postgresql+psycopg2://admin1:88881@localhost:5432/vkinder')
    Session = sessionmaker(bind=engine)
    session = Session()

    def _insert_basics(self) -> None:

        """ Method for writing primary data from files to the database."""

        files = [
            "../db/fix/primary_data.json",
            "../db/fix/countries.json",
            "../db/fix/regions.json",
            "../db/fix/cities.json"
        ]

        table_to_model_mapping = {
            "sex": Sex,
            "status": Status,
            "sort": Sort,
            "country": Country,
            "city": City,
            "region": Region
        }

        # adding data
        additional_fields = {
            "city": {"area": None, "region": None, "important": None}
        }

        for file in files:
            with open(file, encoding='utf-8') as f:
                data = json.load(f)

            by_model = lambda d: d['model']
            for k, group in itertools.groupby(data, by_model):
                group = list(group)

                Model = table_to_model_mapping[k]
                table = Model.__table__

                for object in grouper(tqdm(group, desc=f'Inserting {k}...'), 1000):
                    object = [item for item in object if item]

                    add_data = postgresql.insert(table)

                    primary_keys = [key.name for key in inspect(table).primary_key]
                    update_dict = {c.name: c for c in add_data.excluded if
                                   not c.primary_key}

                    add_data = add_data.on_conflict_do_update(index_elements=primary_keys,
                                                      set_=update_dict)

                    rows = [{**additional_fields.get(k, {}), **ent['fields']} for ent in object]

                    self.session.execute(add_data, rows)
                    self.session.commit()

    def insert_to_db(self, model, fields) -> None:

        """ General method for writing new data to the database """

        entity = model(**fields)
        self.session.add(entity)
        self.session.commit()

    def select_from_db(self, model_fields, expression=None, join=None):

        """ Method for checking the presence of records in the database """

        if not isinstance(model_fields, tuple):
            model_fields = (model_fields,)
        if not isinstance(expression, tuple):
            expression = (expression,)
        if join:
            if not isinstance(join, tuple):
                join = (join,)
            return self.session.query(*model_fields).join(*join).filter(*expression)
        return self.session.query(*model_fields).filter(*expression)

    def update_data(self, model_fields, expression, _fields):
        if not isinstance(model_fields, tuple):
            model_fields = (model_fields,)
        if not isinstance(expression, tuple):
            expression = (expression,)
        self.session.query(*model_fields).filter(*expression).update(_fields)
        self.session.commit()

    def delete_from_db(self, model_fields, expression=None, join=None):

        """ General method for deleting data from DB """

        if not isinstance(model_fields, tuple):
            model_fields = (model_fields,)
        if not isinstance(expression, tuple):
            expression = (expression,)
        self.select_from_db(*model_fields, *expression, join).delete()
        self.session.commit()


# id vk = Primary key

class Country(base):

    __tablename__ = 'country'
    id = Column(Integer, primary_key=True)
    title = Column(String)


class Region(base):

    __tablename__ = 'region'
    id = Column(Integer, primary_key=True)
    title = Column(String)
    country_id = Column(Integer, ForeignKey('country.id'))


class City(base):

    __tablename__ = 'city'
    id = Column(Integer, primary_key=True)
    title = Column(String)
    important = Column(Integer, default=0)
    area = Column(String, default=None)
    region = Column(String)
    region_id = Column(Integer, ForeignKey('region.id'))


class Sex(base):

    __tablename__ = 'sex'
    id = Column(Integer, primary_key=True)
    title = Column(String)


class Status(base):

    __tablename__ = 'status'
    id = Column(Integer, primary_key=True)
    title = Column(String)


class Sort(base):

    __tablename__ = 'sort'
    id = Column(Integer, primary_key=True)
    title = Column(String)


class User(base):

    __tablename__ = 'user'
    id = Column(Integer, primary_key=True)
    first_name = Column(String)
    last_name = Column(String)
    date_of_birth = Column(String)
    city_id = Column(Integer, ForeignKey('city.id'))
    sex_id = Column(Integer, ForeignKey('sex.id'))
    link = Column(String)


class Query(base):

    __tablename__ = 'query'
    id = Column(Integer, primary_key=True, autoincrement=True)
    datetime = Column(DateTime)
    sex_id = Column(Integer, ForeignKey('sex.id'))
    city_id = Column(Integer, ForeignKey('city.id'))
    age_from = Column(Integer)
    age_to = Column(Integer)
    status_id = Column(Integer, ForeignKey('status.id'))
    sort_id = Column(Integer, ForeignKey('sort.id'))
    user_id = Column(Integer, ForeignKey('user.id'))


class DatingUser(base):

    __tablename__ = 'datinguser'
    id = Column(Integer, primary_key=True, autoincrement=True)
    vk_id = Column(Integer)
    first_name = Column(String)
    last_name = Column(String)
    city_id = Column(Integer)
    city_title = Column(String)
    link = Column(String)
    verified = Column(Integer)
    query_id = Column(Integer, ForeignKey('query.id'))
    viewed = Column(Boolean, default=False)
    black_list = Column(Boolean, nullable=True)


if __name__ == '__main__':

    now = datetime.now()
    base.metadata.create_all(Connect.engine)
    print("All tables are created successfully")
    Connect()._insert_basics()
    print("Primary inserts done")
    print(datetime.now() - now)