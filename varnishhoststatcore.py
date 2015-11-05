# coding: utf-8

import varnishapi,time,datetime,os,re,json
import logging,logging.handlers


class varnishHostStat:
	def __init__(self, opts):
		#utils
		#buf -> trx 
		self.buf       = {}
		self.trx       = [{}]
		self.thr       = 10
		self.filter    = False
		self.mode_raw  = False
		self.o_json    = False
		self.log       = False
		self.mode_a    = False
		self.time      = int(time.time())
		self.last      = int(time.time())

		vops = ['-c', '-i', 'Length,RxHeader,RxUrl,TxStatus,ReqEnd,ReqStart,VCL_Call', '-I', '^([0-9]+$|Host:|/|[0-9\. ]+$|[a-z]+$)']
		arg = {}
		for o,a in opts:
			if   o == '-i' and a.isdigit():
				self.thr = int(a)
			elif o == '-w':
				lg       = logging.handlers.WatchedFileHandler(a)
				lg.setLevel(logging.INFO)
				lg.setFormatter(logging.Formatter("%(message)s"))
				self.log = logging.getLogger()
				self.log.addHandler(lg)
				self.log.setLevel(logging.INFO)
			elif o == '-r':
				self.mode_raw = True
			elif o == '-a':
				self.mode_a   = True
			elif o == '-j':
				self.o_json = True
			elif o == '-n':
				vops += ['-n', a]
			elif o == '--start':
				start      = int(a)
				ns         = datetime.datetime.today().second
				if start > ns:
					wait   = start - ns
				elif start == ns:
					wait   = 0
				else:
					wait   = 60 - ns + start
				if wait > 0:
					self.time += wait
					self.last += wait
					time.sleep(wait)
			elif o == '--sopath':
				arg["sopath"] = a
			elif o == '-F':
				spl = a.split('@' ,2)
				tmp = [a, spl[0]]
				if len(spl) == 2:
					tmp.append(re.compile(spl[1]))
				else:
					tmp.append(False)
				if not self.filter: 
					self.filter = []
				self.filter.append(tmp)
		if self.mode_a and not self.filter:
			self.mode_a = False
			print "Disabled -a option. Bacause -F option is not specified."

		arg["opt"]   = vops
		self.vap     = varnishapi.VarnishAPI(**arg)
		self.vslutil = varnishapi.VSLUtil()
	

	def execute(self):
		while 1:
			#dispatch
			self.vap.VSL_NonBlockingDispatch(self.vapCallBack)
			cmp = self.makeCmpData()
			if cmp:
				txt = self.txtCmp(cmp)
				self.outTxt(txt)

			time.sleep(0.1)
			if int(time.time()) - self.last > 5:
				self.vap.VSM_ReOpen()
				self.last  = int(time.time())

	def makeCmpData(self):
		now   = int(time.time())
		delta = int((now - self.time)/self.thr)
		if delta >= 1:
			tmp   = {}
			total = {}
			while len(self.trx) > 0:
				pl = self.trx.pop(0)
				for host,v in pl.items():
					if host not in tmp:
						tmp[host] = {}
					for key,val in v.items():
						if key not in tmp[host]:
							tmp[host][key] = 0
						tmp[host][key] += val
						if host[0:3] != "[AF":
							if key not in total:
								total[key] = 0
							total[key]     += val
			otime     = self.time
			self.time = now
			if len(total) == 0:
				return {'@start-time':otime, '@end-time':now -1}
			tmp['#alldata']    = total
			tmp['@start-time'] = otime
			tmp['@end-time']   = now -1
			if self.mode_raw:
				return tmp
			for host, v in tmp.items():
				if host[0] == '@':
					continue
				tmp[host]['mbps']    = float(v['totallen'])     / self.thr  * 8 / 1024 / 1024
				tmp[host]['rps']     = float(v['req'])          / self.thr
				if v['req'] > 0:
					tmp[host]['hit']                = (1 - float(v['fetch'])     / v['req']) * 100
					tmp[host]['avg_fsize']          = float(v['totallen'])       / v['req']  / 1024
					tmp[host]['avg_time']           = (float(v['no_fetch_time']) + v['fetch_time']) / v['req']
				else:
					tmp[host]['hit']                = 0.0
					tmp[host]['avg_fsize']          = 0.0
					tmp[host]['avg_time']           = 0.0
				if v['req'] - v['fetch'] > 0:
					tmp[host]['avg_not_fetch_time'] = float(v['no_fetch_time'])  / (v['req'] - v['fetch'])
				else:
					tmp[host]['avg_not_fetch_time'] = 0.0
				if v['fetch'] > 0:
					tmp[host]['avg_fetch_time']     = float(v['fetch_time'])     / v['fetch']
				else:
					tmp[host]['avg_fetch_time']     = 0.0
				tmp[host]['avg_2xx']    = float(v['2xx'])          / self.thr
				tmp[host]['avg_3xx']    = float(v['3xx'])          / self.thr
				tmp[host]['avg_4xx']    = float(v['4xx'])          / self.thr
				tmp[host]['avg_5xx']    = float(v['5xx'])          / self.thr
			return tmp
		else:
			while len(self.trx) -1 < delta:
				self.trx.append({})
			
	def outTxt(self,txt):
		if self.log:
			self.log.info(txt)
		else:
			if not self.o_json:
				os.system('clear')
			print txt

	def txtCmp(self,cmp):
		if self.o_json:
			return json.dumps(cmp, ensure_ascii=False).decode('utf8','ignore')
		else:
			ret = ''
			#os.system('clear')
			ret+= str(datetime.datetime.fromtimestamp(cmp['@start-time'])) + ' - ' + str(datetime.datetime.fromtimestamp(cmp['@end-time'])) + ' (interval:'+ str(self.thr) +')' + "\n"
			if self.mode_raw:
				ret+= "%-50s | %-11s | %-11s | %-11s | %-13s | %-11s | %-11s | %-11s | %-11s | %-11s |\n" % ("Host", "req", "fetch", "fetch_time","no_fetch_time","totallen", "2xx","3xx", "4xx", "5xx")
				ret+= '-' * 179 + "|\n"
				for host in sorted(cmp.keys()):
					if host[0] == '@':
						continue
					v = cmp[host]
					ret+= "%-50s | %11d | %11d | %11f | %13f | %11d | %11d | %11d | %11d | %11d |\n" % (host, v['req'], v['fetch'], v['fetch_time'],v['no_fetch_time'], v['totallen'], v['2xx'], v['3xx'], v['4xx'], v['5xx'] )
			else:
				ret+= "%-50s | %-11s | %-11s | %-11s | %-11s | %-11s | %-11s | %-11s | %-11s | %-11s | %-11s | %-11s |\n" % ("Host", "Mbps", "rps", "hit", "time/req","(H)time/req", "(M)time/req", "KB/req", "2xx/s", "3xx/s", "4xx/s", "5xx/s")
				ret+= '-' * 205 + "|\n"
				for host in sorted(cmp.keys()):
					if host[0] == '@':
						continue
					v = cmp[host]
					ret+= "%-50s | %-11f | %11f | %11f | %11f | %11f | %11f | %11f | %11f | %11f | %11f | %11f |\n" % (host, v['mbps'], v['rps'], v['hit'], v['avg_time'], v['avg_not_fetch_time'], v['avg_fetch_time'], v['avg_fsize'], v['avg_2xx'], v['avg_3xx'], v['avg_4xx'], v['avg_5xx'])
			return ret
			


	def chkFilter(self, dat, forceHost=False, Prefix='[F'):
		if not self.filter or forceHost:
			return dat['Host']
		i = 0
		for v in self.filter:
			i   += 1
			host = v[1]
			reg  = v[2]
			if dat['Host'].endswith(host) and (not reg or reg.match(dat['url'])):
				return Prefix + str(i) + ']' + v[0]

	def appendTrx(self, host,nfd,  delta):
		if delta < 0 or not host:
			return

		while len(self.trx) -1 < delta:
			self.trx.append({})
		if host not in self.trx[delta]:
			self.trx[delta][host] = {'req':0, 'fetch':0, 'fetch_time':0.0,'no_fetch_time':0, 'totallen':0,'2xx':0,'3xx':0,'4xx':0,'5xx':0}

		self.trx[delta][host]['req']          += 1
		self.trx[delta][host]['totallen']     += self.buf[nfd]['Length']

		status = self.buf[nfd]['status']
		
		if status >= 200:
			if   status < 300:
				self.trx[delta][host]['2xx'] += 1
			elif status < 400:
				self.trx[delta][host]['3xx'] += 1
			elif status < 500:
				self.trx[delta][host]['4xx'] += 1
			elif status < 600:
				self.trx[delta][host]['5xx'] += 1

		if self.buf[nfd]['fetch']:
			self.trx[delta][host]['fetch_time']    += self.buf[nfd]['worktime']
			self.trx[delta][host]['fetch']         += 1
		else:
			self.trx[delta][host]['no_fetch_time'] += self.buf[nfd]['worktime']

	def vapCallBack(self, priv, tag, fd, length, spec, ptr, bm):
		self.last = int(time.time())
		if spec == 0:
			return

		nml  = self.vap.normalizeDic(priv, tag, fd, length, spec, ptr, bm)
		ntag = nml['tag']
		nfd  = str(nml['fd'])
		nmsg = nml['msg']

		if   ntag == 'ReqStart':
			self.buf[nfd] = {'Host':'#n/a', 'Length':0,'url':'','status':0,'fetch':0,'time':0.0,'worktime':0.0}
		elif nfd in self.buf:
			if ntag == 'VCL_call':
				if nmsg == 'fetch':
					self.buf[nfd]['fetch']  = 1 
			elif ntag == 'Length':
				self.buf[nfd]['Length'] = int(nmsg)
			elif ntag == 'RxURL':
				self.buf[nfd]['url']    = nmsg
			elif ntag == 'TxStatus':
				self.buf[nfd]['status'] = int(nmsg)
			elif ntag == 'ReqEnd':
				spl = nmsg.split(' ',4)
				self.buf[nfd]['worktime']   = float(spl[2]) - float(spl[1])
				self.buf[nfd]['time']       = int(float(spl[2])) #EndTime
				delta                       = int((self.buf[nfd]['time'] - self.time) / self.thr)
				
				if self.mode_a:
					self.appendTrx(self.chkFilter(self.buf[nfd],True) ,nfd , delta)
					self.appendTrx(self.chkFilter(self.buf[nfd],False,'[AF') ,nfd , delta)
				else:
					self.appendTrx(self.chkFilter(self.buf[nfd]) ,nfd , delta)

				#else:
				#	print 'delay:'
				del self.buf[nfd]
			elif ntag == 'RxHeader':
				self.buf[nfd]['Host']   = nmsg.split(':', 2)[1].strip()



