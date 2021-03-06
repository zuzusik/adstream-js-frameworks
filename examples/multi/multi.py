#!/usr/bin/python

import os, urllib, re, sys, traceback, string, time, random
import simplejson as json

random.seed()

def namedParameters():
    result = {}
    for i in sys.argv:
        m = re.match( r'--([a-zA-Z]+)(?:=(.+))?', i )
        if m:   result[ m.group(1) ] = (lambda x: x if x != None else True)( m.group(2) )
    return result

def decodeURLParamValue( value ):
	value = urllib.unquote( value )
	try:
		value = int(value)
	except ValueError:
		value = unicode(value,'utf8')
	return value

def decodeURLParam( p ):
    name,value = p.split( '=', 1 )
    return (name, decodeURLParamValue(value))
            
def as_json(f):
	def wrapper( *args, **kwargs ):
		kwargs['headers']['Content-Type'] = 'application/json'
		return json.dumps( f( *args, **kwargs ) )
	return wrapper

def json_input(f):
	def wrapper( env, *args, **kwargs ):
		return f( json.loads( env['wsgi.input'].read( int(env['CONTENT_LENGTH']) ) ), *args, **kwargs )
	return wrapper

def no_input(f):
	def wrapper( env, *args, **kwargs ):
		return f( *args, **kwargs )
	return wrapper

class HTTPError (Exception):

	httpStatusCodes = {
		200: 'OK', 400: 'BAD REQUEST', 401: 'UNAUTHORIZED', 404: 'NOT FOUND', 
		405: 'METHOD NOT ALLOWED', 409: 'CONFLICT', 410: 'GONE', 500: 'INTERNAL ERROR'
	}

	def __init__( self, code, message, response = {} ):
		self.response = response
		self.status = str(code) + ' ' + HTTPError.httpStatusCodes.get( code, 'ERROR' )
		self.response.setdefault( '_error', {} )['message'] = message

	def result(self):
		return json.dumps( self.response )

##########################################################

localpath = os.path.abspath(os.path.dirname(__file__))

@no_input
def getStatic( path_name, headers={}, **kwargs ):
	m = re.search( '[.]([^.]*)$', path_name )
	if m:
		headers['Content-Type'] = {
			'html': 'text/html', 'css': 'text/css', 'js': 'application/javascript',
			'gif': 'image/gif', 'jpeg': 'image/jpeg', 'png': 'image/png',
			'zip': 'application/zip'
		}.get( m.group(1).lower(), 'text/plain' )
	
	path = os.path.abspath( os.path.join( localpath, path_name ) )

	return open( path, 'r' )

@no_input
@as_json
def getRows( offset=0, count=10, depth=999, **kwargs ):
	return { 'rows': dict( ( (str(i), _getRow( i, depth-1 )) for i in xrange(offset,offset+count) ) ) }

def _getRow( row, depth, **kwargs ):
	if depth <= 0: return {}
	return { 'cols': _getCols( row, **kwargs ) }

@no_input
@as_json
def getRow( row, depth=999, **kwargs ):
	result = {}
	result[ 'rows/' + str(row) ] = _getRow( row, depth, **kwargs )
	return result

def _getCols( row, offset=0, count=10, **kwargs ):
	return dict( ( (str(i), _getCol( row, i )) for i in xrange(offset,offset+count) ) )

@no_input
@as_json
def getCols( row, **kwargs ):
	result = {}
	result[ 'rows/' + str(row) + '/cols' ] = _getCols( row, **kwargs )
	return result

def _getCol( row, col ):
	return { 'value': (int(row)+1)*(int(col)+1) }

@no_input
@as_json
def getCol( row, col, **kwargs ):
	result = {}
	result[ 'rows/' + str(row) + '/cols/' + str(col) ] = _getCol( row, col )
	return result

##########################################################

urlMap = [
	( re.compile( r'^/rows/?$' ), { 'GET': getRows } ),
	( re.compile( r'^/rows/(\d+)$' ), { 'GET': getRow } ),
	( re.compile( r'^/rows/(\d+)/cols/?$' ), { 'GET': getCols } ),
	( re.compile( r'^/rows/(\d+)/cols/(\d+)$' ), { 'GET': getCol } ),
	( re.compile( r'^/static/+(.*)$' ), { 'GET': getStatic } )
]

def dispatch( path, method, env, headers, kwargs ):
	for i in urlMap:
		m = i[0].match( path ) 
		if m:
			if method in i[1]:
				kwargs['headers'] = headers
				return i[1][method]( env, *m.groups(), **kwargs )
			else:
				raise HTTPError( 405, method + ' not valid for ' + path )
	
	raise HTTPError( 404, path + ' not found' )

def wsgi_application( env, wsgi_cb ):

	try:
		
		headers = {}

		result = dispatch( 
			env['PATH_INFO'], env['REQUEST_METHOD'], env, headers,
			dict(( decodeURLParam( p ) for p in env['QUERY_STRING'].split('&') if p ))
		)

		if 'Content-Type' not in headers:	headers['Content-Type'] = 'text/plain'

		wsgi_cb( '200 OK', headers.items() )
		return result

	except HTTPError as err:
		wsgi_cb( err.status, [ ('Content-Type','application/json') ] )
		return err.result()
	except:
		traceback.print_exc()
		err = HTTPError( 500, ''.join( traceback.format_exception_only( sys.exc_info()[0], sys.exc_info()[1] ) ), 
						 { '_error': { 'traceback': traceback.format_tb( sys.exc_info()[2] ) } } )
		wsgi_cb( err.status, [ ('Content-Type','application/json') ] )
		return err.result()		

if __name__=="__main__":
    
	params = namedParameters()
	port = params.get('socket', 8080)

	from twisted.web import server
	from twisted.web.wsgi import WSGIResource
	from twisted.python.threadpool import ThreadPool
	from twisted.python import log
	from twisted.internet import reactor
	from twisted.application import service, strports

	# Create and start a thread pool,
	wsgiThreadPool = ThreadPool()
	wsgiThreadPool.start()

	# ensuring that it will be stopped when the reactor shuts down
	reactor.addSystemEventTrigger('after', 'shutdown', wsgiThreadPool.stop)

	reactor.listenTCP( port, server.Site( WSGIResource(reactor, wsgiThreadPool, wsgi_application) ) )
	log.startLogging( log.FileLogObserver( sys.stderr ) )
	reactor.run()

