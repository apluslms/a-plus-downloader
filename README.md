# a-plus-downloader

Script for downloading student data from an [A+](https://github.com/apluslms/a-plus) course.
You can download data for all students or some of them, or all data for your own user account.
The script downloads data to a directory structure like this:
`course/user/module/exercise/submission`.

The data includes submitted files and metadata about the modules, exercises
and submissions (including the points).

## Usage example

Create a Python virtual environment and install the dependencies.

```sh
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy your personal A+ access token (`XYZ`) from your A+ user profile page.
This example downloads data for student with the student ID `123456` in
the course with A+ course instance ID `150` into the directory `downloads`.

```sh
./aplus_downloader.py set-domain --api-token XYZ plus.cs.aalto.fi
./aplus_downloader.py download -c id=150 -u sid=123456 downloads
```

A+ Downloader saves the domain and token settings in the configuration file
`_config/config.ini`.

The A+ ids of courses can be found in the A+ API at
`https://aplusdomain/api/v2/courses/`. In the Aalto University case, the direct
URL is https://plus.cs.aalto.fi/api/v2/courses/.
The parameter `sid` specifies the university-wide student ID.
Aalto University student IDs are six digits, or in older IDs, five digits
following an uppercase alphabet. If you want to specify students by A+ user
ID, use the subparameter `id` instead.

The `sid` can be used multiple times to include multiple students.

If you later want to re-run the script to download later submissions from the
same students, you must first clear the local cache. This is done with
the command:

```sh
rm -rf _cache
```

It seems that this is required because the A+ downloader uses an exercise score
cache to iterate through submissions, but if the cache directory exists,
it is not updated.

