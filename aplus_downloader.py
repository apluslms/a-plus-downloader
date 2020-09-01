#!/usr/bin/env python3
import click
import configparser
import logging
import textwrap
from io import StringIO
from collections import OrderedDict
from collections.abc import MutableMapping
from ruamel.yaml import YAML
from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.scalarstring import PreservedScalarString
from aplus_client.client import AplusTokenClient
from aplus_client.cache import FilesystemCache, InMemoryCache
from urllib.parse import quote_plus as quote, urlsplit
import os

def makedirs(path):
    if not os.path.exists(path):
        os.makedirs(path)

logger = logging.getLogger('aplus_download')
LOG_LEVELS = [logging.WARNING, logging.INFO, logging.DEBUG]
logging.basicConfig(
    level=LOG_LEVELS[0],
    format="%(asctime)-15s %(levelname)-8s %(name)s: %(message)s",
)


class Representer(RoundTripRepresenter):
    pass
Representer.add_representer(OrderedDict, Representer.represent_dict)

def wrap_yaml_string(s, width=100):
    ss = (l.rstrip() for l in s.splitlines())
    ss = (l for l in ss if l)
    #ss = textwrap.wrap('\n'.join(ss), width=width, drop_whitespace=False, tabsize=2)
    return PreservedScalarString('\n'.join(ss))

yaml = YAML(typ='rt')
yaml.Representer = Representer
yaml.compact()
yaml.default_flow_style=False

def yaml_dumps(document):
    stream = StringIO()
    yaml.dump(document, stream)
    return stream.getvalue()

def write_yaml(dir_, fn, data):
    if not os.path.exists(dir_):
        os.makedirs(dir_)
    with open(os.path.join(dir_, fn), 'w') as f:
        yaml.dump(data, f)


__version__ = '0.0.1-a.1'
__author__ = 'io.github.apluslms'
__app_id__ = 'io.github.apluslms.a-plus-downloader'

#import appdirs
#DATA_DIR = appdirs.user_data_dir(appname=__app_id__, appauthor=__author__)
#CONFIG_DIR = appdirs.user_config_dir(appname=__app_id__, appauthor=__author__)
#CACHE_DIR = appdirs.user_cache_dir(appname=__app_id__, appauthor=__author__)
DATA_DIR = '_data'
CONFIG_DIR = '_config'
CACHE_DIR = '_cache'
RESULTS = 'downloaded'
#del appdirs
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.ini')


config = configparser.ConfigParser()
config.read(CONFIG_FILE)


def safe_config():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
    with open(CONFIG_FILE, 'w') as f:
        config.write(f)


@click.group()
@click.option('-v', '--verbose', count=True)
def main(verbose):
    verbose = min(verbose, len(LOG_LEVELS)-1)
    logging.getLogger().setLevel(LOG_LEVELS[verbose])


@main.command()
@click.argument('domain')
@click.option('--api-url', 'api')
@click.option('--api-token', 'token')
@click.option('--login-url', 'login')
def set_domain(domain, api, token, login):
    if 'main' not in config:
        config['main'] = {}
    config['main']['domain'] = domain
    if domain not in config:
        config[domain] = {}
    if api:
        config[domain]['api-url'] = api
    if token:
        config[domain]['api-token'] = token
    if login:
        config[domain]['login-url'] = login

    safe_config()


@main.command()
def clear_cache():
    pass

@main.command()
@click.argument('destination', type=click.Path(file_okay=False, resolve_path=True))
@click.option('-c', '--courses', multiple=True)
@click.option('-u', '--users', multiple=True)
def download(destination, courses, users):
    # domain and token
    domain = config.get('main', 'domain')
    if not domain:
        raise RuntimeError("no domain, run `set-fomain` first")
    token = config.get(domain, 'api-token')
    if not token:
        raise RuntimeError("no api token, run `set-domain` first")

    # api client
    api = AplusTokenClient(token, cache=FilesystemCache(os.path.join(CACHE_DIR, domain)))
    base_url = config.get(domain, 'api-url', fallback='https://%s/api/v2' % (domain,))
    api.set_base_url_from(base_url)
    me = api.load_data('/me/', skip_cache=True)

    # courses
    if not courses:
        courses = me['enrolled_courses']
    else:
        course_ids = set()
        course_urls = set()
        for filter_ in courses:
            key, value = filter_.split('=', 1)
            if key == 'id':
                course_ids.add(int(value))
            elif key == 'url':
                course_urls.add(value.strip('/'))
            else:
                raise ValueError("Unsupported course filter %r. id= and url= are supported" % (key,))
        courses = [api.load_data('/courses/%d/' % i) for i in course_ids]
        course_urls -= set(get_course_url(c) for c in courses)
        if course_urls:
            for course in api.load_data('/courses/'):
                url = get_course_url(course)
                if url in course_urls:
                    courses.append(course)
                    course_urls.remove(url)
                    if not course_urls:
                        break
        if course_urls:
            raise ValueError("Course urls %s were not found" % (course_urls,))
    if not courses:
        raise ValueError("No courses selected")

    print("Selected courses:")
    for course in courses:
        print("  {c.code} - {c.name} ({c.instance_name}) <{c.html_url}>".format(c=course))

    # users
    if not users:
        users = [me]
    else:
        user_ids = set()
        user_sids = set()
        for filter_ in users:
            key, value = filter_.split('=', 1)
            if key == 'id':
                user_ids.add(int(value))
            elif key == 'sid':
                user_sids.add(value.strip().lower())
            else:
                raise ValueError("Unsupported course filter %r. id and sid are supported" % (key,))
        users = [api.load_data('/users/%d/' % i) for i in user_ids]
        user_sids -= set(u.student_id.lower() for u in users)
        if user_sids:
            for course in courses:
                for student in course.students:
                    if student.student_id and student.student_id.lower() in user_sids:
                        users.append(student)
                        user_sids.remove(student.student_id.lower())
                        if not user_sids:
                            break
                if not user_sids:
                    break
        if user_sids:
            raise ValueError("Student ids %s were not found on any courses" % (user_sids,))
    if not users:
        raise ValueError("No users selected")

    print("Selected users:")
    for user in users:
        print("  {u.student_id}: {u.full_name} <{u.email}> (id={u.id})".format(u=user))


    # crawl submissions using points cache
    submission_count = 0
    for course in courses:
        course_dir = "{c.code} - {c.name} ({c.instance_name}) (id={c.id})".format(c=course)
        for user in users:
            points = api.load_data('/courses/%d/points/%d/' % (course.id, user.id))
            name = ("{u.last_name}, {u.first_name} ({u.student_id})" if user.get('student_id') else "{u.last_name}, {u.first_name} (id={u.id})").format(u=user)
            if not points:
                raise ValueError("User %s is not enrolled on the course %s" % (name, course_dir))
            user_dir = os.path.join(destination, course_dir, name)
            user_data = dict_from_api(points, 'student_id', 'full_name', 'first_name', 'last_name', 'email', ('api_url', 'url'))
            user_data['tags'] = [(t.name, t.description) for t in points['tags']]
            user_data.update(dict_from_api(points, 'submission_count', 'points', 'points_by_difficulty'))
            write_yaml(user_dir, 'user.yaml', user_data)

            for module in points['modules']:
                exercises = module['exercises']
                if not exercises:
                    continue

                module_name = "{} (id={})".format(module.name[:40], module.id)
                module_dir = os.path.join(user_dir, module_name)
                module_data = dict_from_api(module, 'id', 'name', 'submission_count', 'passed', 'max_points', 'points_to_pass', 'points', 'points_by_difficulty')
                write_yaml(module_dir, 'module.yaml', module_data)

                for exercise in exercises:
                    exercise_name = "{} (id={})".format(exercise.name[:40], exercise.id)
                    exercise_dir = os.path.join(module_dir, exercise_name)
                    exercise_data = dict_from_api(exercise, 'id', ('api_url', 'url'), 'name', 'difficulty', 'submission_count', 'passed', 'max_points', 'points_to_pass', 'points')

                    submissions = exercise['submissions']
                    if not submissions:
                        write_yaml(module_dir, exercise_name + '.yaml', exercise_data)
                    else:
                        write_yaml(exercise_dir, 'exercise.yaml', exercise_data)
                        best_url = exercise['best_submission']
                        for submission_url in submissions:
                            best = submission_url == best_url
                            submission = api.load_data(submission_url)
                            download_submission(api, submission, exercise_dir, best=best)
                            submission_count += 1

    print("DONE. Downloaded %d submissions" % submission_count)
    return


    # OLD METHOD

    # find all submission API points
    data = {}
    for course in courses:
        info = "{c.code} - {c.name} ({c.instance_name}) (id={c.id})".format(c=course)
        subs = []
        data[info] = subs

        for module in course['exercises']:
            for exercise in module['exercises']:
                if 'submissions' not in exercise:
                    continue
                url = exercise.get_item('submissions')
                if not url.endswith('/'):
                    url += '/'
                subs.append(url)

    from pprint import pprint
    pprint(data)

    # download all submissions for all users in all endpoints
    for info, submission_urls in data.items():
        for user in users:
            name = user['student_id'] or ('aplus_%d' % user.id)
            user_data = dict_from_api(user, 'student_id', 'email', 'first_name', 'last_name', 'full_name')
            for url in submission_urls:
                for submission in api.load_data('%s%d/' % (url, user.id)) or []:
                    ename = get_exercise_fn(submission.exercise, dirs=1)
                    path = os.path.join(destination, info, name, ename)
                    if not os.path.exists(path):
                        os.makedirs(path)
                    download_submission(api, submission, path)


def download_submission(api, submission, base_dir, best=False):
    form = SubmissionForm(submission)
    submission_data = OrderedDict()
    submission_data['exercise'] = dict_from_api(submission['exercise'], ('name', 'display_name'), 'max_points', 'max_submissions')
    submission_data.update(dict_from_api(submission, 'submission_time', 'grading_time', 'status', 'grade', 'late_penalty_applied'))
    submission_data['form'] = form.as_list()
    submission_data.update(dict_from_api(submission, 'grader'))
    for k, s in dict_from_api(submission, 'assistant_feedback', 'feedback').items():
        submission_data[k] = wrap_yaml_string(s) if s else s
    submission_name = ("{s.submission_time} (best)" if best else "{s.submission_time}").format(s=submission)
    base_fn = os.path.join(base_dir, submission_name)
    if not form.has_files:
        yaml_fn = base_fn + '.yaml'
    else:
        yaml_fn = os.path.join(base_fn, '_meta.yaml')
        if not os.path.exists(base_fn):
            os.makedirs(base_fn)
    for extra_fn, url in form.iter_files():
        api.load_file(os.path.join(base_fn, extra_fn), url)
        print(" -- wrote", os.path.join(base_fn, extra_fn))
        # if any files would be the same name, write to default location
        if extra_fn == '_meta.yaml':
            yaml_fn = base_fn + '.yaml'
    with open(yaml_fn, 'w') as f:
        yaml.dump(submission_data, f)
    print(" -- wrote", yaml_fn)


def dict_from_api(api, *fields):
    dict_ = OrderedDict()
    for field in fields:
        if isinstance(field, tuple):
            key, field = field
        else:
            key = field
        while api and '.' in field:
            get, field = field.split('.', 1)
            api = api.get(get, None)
        dict_[key] = api.get_item(field, None)
    return dict_


def get_course_url(course):
    return '/'.join(course.html_url.split('/')[-3:-1])


EXERCISE_FN_CACHE = InMemoryCache(maxsize=1000)
def get_exercise_fn(exercise, dirs=0):
    """
    Path component in A+ is horrible, so try to clean it a bit.
    Sadly, this means that the filenames do not match correctly with the url.
    """
    if exercise.id in EXERCISE_FN_CACHE:
        return EXERCISE_FN_CACHE[exercise.id]
    path = [p for p in urlsplit(exercise.html_url).path.split('/') if p]
    cleaned = []
    while path:
        cur = path[0]
        curl = len(cur)
        path = [p[curl:].lstrip('_-.') if p.startswith(cur) else p for p in path[1:]]
        cleaned.append(cur)
    cleaned = cleaned[2:]
    name = "%s (%d)" % (quote('-'.join(cleaned)), exercise.id)
    components = []
    while (dirs > 0 or len(name) > 250) and len(cleaned) > 1:
        dirs -= 1
        components.append(cleaned[0])
        cleaned = cleaned[1:]
        name = "%s (id=%d)" % (quote('-'.join(cleaned)), exercise.id)
    fn = os.path.join(*components, name)
    EXERCISE_FN_CACHE[exercise.id] = fn
    return fn


class SubmissionForm:
    def __init__(self, submission, lang='en'):
        self.submission = submission
        exc_info = submission.exercise.get_item('exercise_info', None) or {}
        spec = exc_info.get('form_spec', None) or ()
        i18n = exc_info.get('form_i18n', None) or {}
        data = submission.get_item('submission_data', None) or ()
        files = submission.get_item('files', None) or ()

        self.spec = spec
        self.i18n = {key: (value[lang] if lang in value else value.values()[0]) for key, value in i18n.items()}
        self.fields = {f['key']: f for f in spec if 'key' in f}
        self.data = OrderedDict()
        self.has_files = bool(files)
        for key, value in data:
            self.data.setdefault(key, []).append(value)
            if key not in self.fields:
                self.fields[key] = None
        for file_ in files:
            key = file_.pop('param_name', None)
            self.data.setdefault(key, []).append(file_)
            if key not in self.fields:
                self.fields[key] = {'type': 'file', 'key': key}

        self._type_handlers = {
           'radio': self._field_choice,
           'checkbox': self._field_choice,
        }

    def keys(self):
        return self.fields.keys()

    def __iter__(self):
        yield from self.keys()

    def __getitem__(self, key):
        field = self.fields[key]
        datas = self.data[key]
        if field:
            datas = self._handle_item(key, field, datas)
        return field, datas

    def gettitle(self, key):
        field = self.fields[key]
        title = field.get('title', key)
        return self.i18n.get(title, title)

    def _handle_item(self, key, field, datas):
        type_ = field.get('type')
        if type_ and type_ in self._type_handlers:
            datas = self._type_handlers[type_](key, field, datas)
        return datas

    def _field_choice(self, key, field, datas):
        values = []
        for value in datas:
            if value in field.get('titleMap', ()):
                txt = field['titleMap'][value]
                txt = self.i18n.get(txt, txt)
                value = "{}) {}".format(value, txt)
            values.append(value)
        return values

    def as_list(self):
        data = []
        for key in self:
            datas = self.data.get(key, [])
            field = self.fields[key]
            if field:
                title = field.get('title', key)
                title = self.i18n.get(title, title)
                type_ = field.get('type')
                datas = self._handle_item(key, field, datas)
                data.append((title, type_, datas))
            else:
                data.append((key, datas))
        return data

    def iter_files(self):
        for key in self:
            field = self.fields[key]
            if field and field.get('type') == 'file':
                for item in self.data[key]:
                    url = item.get('url')
                    # FIXME: title is best current available place for filename used in grader
                    fn = field.get('title') or item.get('filename') or key
                    yield (fn, url)


if __name__ == '__main__':
    main()
