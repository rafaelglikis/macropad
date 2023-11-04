from Profile import Profile
from interceptor import listen


def main():
    try:
        listen(Profile())
    except KeyboardInterrupt:
        print('Keyboard interrupt exiting')
        return


if __name__ == '__main__':
    main()
