# Copyright 2013 Pawel Daniluk, Bartek Wilczynski
# 
# This file is part of WeBIAS.
# 
# WeBIAS is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as 
# published by the Free Software Foundation, either version 3 of 
# the License, or (at your option) any later version.
# 
# WeBIAS is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
# 
# You should have received a copy of the GNU Affero General Public 
# License along with WeBIAS. If not, see 
# <http://www.gnu.org/licenses/>.

import cherrypy
import config

import time

import data 

import auth

import sys
import traceback

from util import *

def hit_recorder():
    if sys.exc_info()[0]==cherrypy._cperror.InternalRedirect:
        status='XXX Internal redirect'
        stat_num=0
    elif cherrypy.response.status==None:
        status='500 Internal Server Error'
        stat_num=500
    else:
        status=cherrypy.response.status
        stat_num=int(status.split(' ')[0])

    session=cherrypy.request.db
    login=auth.get_login()

    if login!=None:
        user=data.User.get_by_login(session, login)
        user_id=user.id
    else:
        user_id=None
    
    date=time.strftime("%Y-%m-%d %H:%M:%S")
    ip_address=cherrypy.request.remote.ip

    url = cherrypy.url(qs=cherrypy.request.query_string)

    req_sub=getattr(cherrypy.request, 'req_sub', False)

    hit=data.Hit(user_id, login, date, ip_address, url, status, cherrypy.session.id, req_sub)
    session.add(hit)
    session.commit()

    if stat_num>400:
        error_recorder(hit.id)


cherrypy.tools.hit_recorder = cherrypy.Tool('on_end_resource', hit_recorder, priority=50)


def error_recorder(hit_id=None):
    session=cherrypy.request.db
    engine=None

    if session==None:
        engine= sqlalchemy.create_engine(config.DB_URL, echo=False)
        engine.connect();
        Session=sqlalchemy.orm.sessionmaker(bind=engine)
        session=Session()

    login=auth.get_login()

    if cherrypy.response.status==None:
        status='500 Internal Server Error'
    else:
        status=cherrypy.response.status


    if login!=None:
        user=data.User.get_by_login(session, login)
        user_id=user.id
    else:
        user_id=None
    
    date=time.strftime("%Y-%m-%d %H:%M:%S")
    ip_address=cherrypy.request.remote.ip

    url = cherrypy.url(qs=cherrypy.request.query_string)

    headers=["%s: %s"%(k,v) for k,v in cherrypy.request.header_list]

    request='\n'.join([cherrypy.request.request_line] + headers)
    trace=''.join(traceback.format_exception(*sys.exc_info()))
    
    session_elts=["%s: %s"%(k,v) for k,v in cherrypy.session.items()]
    session_dump='\n'.join(["id: %s"%cherrypy.session.id] + session_elts)

    error=data.Error(user_id, login, hit_id, date, ip_address, url, status, cherrypy.session.id, trace, request, session_dump)
    session.add(error)

    if engine!=None:
        session.commit()
        session.close()


cherrypy.tools.error_recorder = cherrypy.Tool('after_error_response', error_recorder)

class Hits:
    title="Hits"
    caption="Show all HTTP hits."

    @cherrypy.expose
    @persistent
    def index(self, p=1,**kwargs):
        session=cherrypy.request.db

        q=session.query(data.Hit)

        return render_query_paged('statistics_hits.genshi', q, int(p), 'hits', config.APP_ROOT+"/statistics/hits/",kwargs)

class Sessions:
    title="Sessions"
    caption="Show all distinct sessions."

    class CoerceToInt(sqlalchemy.types.TypeDecorator):
        impl = sqlalchemy.types.Integer

        def process_result_value(self, value, dialect):
            if value is not None:
                value = int(value)
            return value

    @cherrypy.expose
    @persistent
    def index(self, p=1):
        session=cherrypy.request.db


#        q=session.query(data.Hit, sqlalchemy.func.count(data.Hit.id), sqlalchemy.func.sum(sqlalchemy.sql.expression.case([(data.Hit.req_sub==True, 1)],else_=0))).group_by(data.Hit.session, data.Hit.ip_address).order_by(data.Hit.id)#.add_column(
        q=session.query(data.Hit, sqlalchemy.func.count(data.Hit.id).label('num_hits'), sqlalchemy.func.sum(sqlalchemy.sql.expression.cast(data.Hit.req_sub, sqlalchemy.types.Integer), type_=self.CoerceToInt).label('num_reqs')).group_by(data.Hit.session, data.Hit.ip_address).order_by(data.Hit.id)#.add_column(
#        q=session.query(data.Hit.date, data.Hit.user_login, data.Hit.ip_address, data.Hit.domain, data.Hit.session, sqlalchemy.func.count(data.Hit.id).label('num_hits'), sqlalchemy.func.sum(sqlalchemy.sql.expression.cast(data.Hit.req_sub, sqlalchemy.types.Integer), type_=CoerceToInt).label('num_reqs')).group_by(data.Hit.session, data.Hit.ip_address).order_by(data.Hit.id)#.add_column(

        return render_query_paged('statistics_sessions.genshi', q, int(p), 'sessions', config.APP_ROOT+"/statistics/sessions/")

    def any_acl(self, *args, **kwargs):
        return ['any']

    @cherrypy.expose
    @auth.with_acl(any_acl)
    def stats(self):

        if auth.get_login()!='admin':
            return ''

        session=cherrypy.request.db
        sub=session.query(data.Hit.session, sqlalchemy.func.count(data.Hit.id).label('num_hits'), sqlalchemy.func.sum(sqlalchemy.sql.expression.cast(data.Hit.req_sub, sqlalchemy.types.Integer), type_=self.CoerceToInt).label('num_reqs')).group_by(data.Hit.session, data.Hit.ip_address).subquery()
        q=session.query(sqlalchemy.func.sum(sub.c.num_hits), sqlalchemy.func.count(sub.c.session), sqlalchemy.func.sum(sub.c.num_reqs))

        stats=q.one()

        return render('statistics_sessions_stats.genshi', num_hits=stats[0], num_sessions=stats[1], num_reqs=stats[2])

        

class Errors:
    title="Errors"
    caption="Show error log."

    @cherrypy.expose
    @persistent
    def index(self, p=1):
        session=cherrypy.request.db

        q=session.query(data.Error)

        return render_query_paged('statistics_errors.genshi', q, int(p), 'errors', config.APP_ROOT+"/statistics/errors/")

    @cherrypy.expose
    @persistent
    def show(self, error_id):
        session=cherrypy.request.db

        err=data.Error.get_error(session, error_id)

        return render('statistics_errors_show.genshi', error=err)


class Statistics:
    _cp_config={
        'tools.secure.on': True,
        'tools.hit_recorder.on': False,
        'tools.protect.allowed': ['admin']
    }

    def __init__(self):
        self.hits=Hits()
        self.errors=Errors()
        self.sessions=Sessions()

    @cherrypy.expose
    @persistent
    def index(self):
        features = dict([(self.__dict__[el].title, {'caption':self.__dict__[el].caption, 'link':el}) for el in self.__dict__ if hasattr(self.__dict__[el], 'title')])

        return render('statistics.genshi', features=features)
