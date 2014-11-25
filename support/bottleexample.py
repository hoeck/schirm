import bottle
import schirmclient

@bottle.route('/hello/<name>')
def index(name):
    return bottle.template('<b>Hello {{name}}</b>!', name=name)

if __name__ == '__main__':
    schirmclient.wsgi_run(url='/hello/schirm', fullscreen=True)
