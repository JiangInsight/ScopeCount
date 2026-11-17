
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
using namespace std;
using U=uint64_t;using I=uint32_t;using Clock=chrono::steady_clock;
long long elapsed(Clock::time_point t){return chrono::duration_cast<chrono::nanoseconds>(Clock::now()-t).count();}
struct Range{I l,r;bool operator==(const Range&)const=default;};
struct Q{string id;U one,zero;vector<Range> ranges;};
struct Node{int a=-1,b=-1,bit=-1;U shape=0,all=0,any=0;vector<I> p,pref;vector<U>w;
 I rank(I x)const{return w.empty()?I(lower_bound(p.begin(),p.end(),x)-p.begin()):pref[x>>6]+(x%64?popcount(w[x/64]&((U(1)<<(x%64))-1)):0);}
 I count(Range z)const{return rank(z.r)-rank(z.l);}
};
struct Tree{
 vector<Node> t;I n;
 int grow(vector<U> s){int x=int(t.size());t.emplace_back();if(s.size()==1){t[x].shape=t[x].all=t[x].any=s[0];return x;}
 int best=-1,bal=0;for(int k=0;k<64;k++){int a=0;for(U v:s)a+=int(v>>k&1);int sc=min(a,int(s.size())-a);if(sc>bal){best=k;bal=sc;}}
 if(best<0)throw runtime_error("duplicate shape");
 vector<U>a,b;for(U v:s)(v>>best&1?b:a).push_back(v);
 int i=grow(move(a)),j=grow(move(b));t[x].bit=best;t[x].a=i;t[x].b=j;t[x].all=t[i].all&t[j].all;t[x].any=t[i].any|t[j].any;return x;}
 Tree(const vector<U>&rows):n((I)rows.size()){
 vector<U>s=rows;sort(s.begin(),s.end());s.erase(unique(s.begin(),s.end()),s.end());grow(move(s));
 for(I i=0;i<n;i++){int x=0;while(t[x].bit>=0){x=(rows[i]>>t[x].bit&1)?t[x].b:t[x].a;t[x].p.push_back(i);}}
 for(auto &v:t)if(!v.p.empty()&&4ULL*v.p.size()>12ULL*((U(n)+63)/64)+4){v.w.assign((U(n)+63)/64,0);for(I i:v.p)v.w[i/64]|=U(1)<<(i%64);
 v.pref.resize(v.w.size()+1);for(size_t k=0;k<v.w.size();k++)v.pref[k+1]=v.pref[k]+popcount(v.w[k]);vector<I>().swap(v.p);}}
};
struct Term{int x,plus,minus;};
using Plan=vector<Term>;
vector<int> leaflabels(const Tree&t,const vector<Q>&qs){vector<int>s(t.t.size());for(size_t x=0;x<t.t.size();x++)if(t.t[x].bit<0){U v=t.t[x].shape;for(int j=0;j<int(qs.size());j++)if((v&qs[j].one)==qs[j].one&&!(v&qs[j].zero))s[x]|=1<<j;}return s;}
const int BIG=100000000;


void validatePrices(const Tree&t,int b,int a,int c,const vector<pair<int,int>>*price=nullptr){
 if(b<1||b>8||t.t.empty()||(price&&price->size()!=t.t.size())||a<0||c<0)throw invalid_argument("invalid price schedule");
 int64_t bound=0;for(size_t x=1;x<t.t.size();x++){int A=price?(*price)[x].first:a,C=price?(*price)[x].second:c;
 if(A<0||C<0)throw invalid_argument("negative edge price");bound+=A+int64_t(b)*C;
 if(bound>=BIG/2)throw overflow_error("price schedule exceeds exact integer kernel range");}}
Plan solveValidatedPrices(const Tree&t,const vector<int>&leaf,int b,int defaultA,int defaultC,bool brute=false,const vector<pair<int,int>>*price=nullptr){
 int k=1<<b;vector<vector<int>>msg(t.t.size());vector<vector<uint16_t>>arg(t.t.size(),vector<uint16_t>(k));
 for(int x=int(t.t.size())-1;x>=0;x--){auto &v=t.t[x];int A=price?(*price)[x].first:defaultA,c=price?(*price)[x].second:defaultC;vector<int> f(k);
 for(int s=0;s<k;s++) f[s]=v.bit<0?(s==leaf[x]?0:BIG):msg[v.a][s]+msg[v.b][s];
 if(v.bit>=0){vector<int>().swap(msg[v.a]);vector<int>().swap(msg[v.b]);}
 auto &d=msg[x];d=f;auto& h=arg[x];for(int s=0;s<k;s++)h[s]=uint16_t(s);
 if(!x){int j=int(min_element(f.begin(),f.end())-f.begin());h[0]=uint16_t(j);continue;}
 if(brute){for(int s=0;s<k;s++)for(int j=0;j<k;j++){int z=f[j]+(j==s?0:A+c*popcount(unsigned(j^s)));if(z<d[s]){d[s]=z;h[s]=uint16_t(j);}}continue;}
 for(int i=0;i<b;i++)for(int s=0;s<k;s++)if(!(s&(1<<i))){int j=s|(1<<i);
 if(d[s]>d[j]+c){d[s]=d[j]+c;h[s]=h[j];}else if(d[j]>d[s]+c){d[j]=d[s]+c;h[j]=h[s];}}
 for(int s=0;s<k;s++)if(f[s]<=d[s]+A){d[s]=f[s];h[s]=uint16_t(s);}else d[s]+=A;
 }
 Plan p;auto visit=[&](auto&&self,int x,int par)->void{int s=arg[x][par];if(s!=par)p.push_back({x,s&~par,par&~s});auto &v=t.t[x];if(v.bit>=0){self(self,v.a,s);self(self,v.b,s);}};visit(visit,0,0);return p;
}
Plan optimize(const Tree&t,const vector<int>&leaf,int b,int a,int c,bool brute=false,const vector<pair<int,int>>*price=nullptr){
 validatePrices(t,b,a,c,price);if(leaf.size()!=t.t.size())throw invalid_argument("incorrect label count");
 for(size_t x=0;x<t.t.size();x++)if(t.t[x].bit<0&&(leaf[x]<0||leaf[x]>=(1<<b)))throw invalid_argument("leaf label out of domain");
 return solveValidatedPrices(t,leaf,b,a,c,brute,price);}
Plan separate(const Tree&t,const vector<int>&lab,int b){map<int,pair<int,int>> m;for(int j=0;j<b;j++){
 vector<int> l=lab;for(int &s:l)s=(s>>j)&1;
 for(auto z:solveValidatedPrices(t,l,1,1,1)){m[z.x].first|=z.plus<<j;m[z.x].second|=z.minus<<j;}}
 Plan p;for(auto [x,e]:m)p.push_back({x,e.first,e.second});return p;}

template<class Topo>Plan fitch(const Topo&t,const vector<int>&lab,int b,bool nearest){
 using Set=array<U,4>; vector<Set> S(t.t.size());const int words=((1<<b)+63)/64;
 for(int x=int(S.size())-1;x>=0;x--){auto&v=t.t[x];if(v.bit<0){S[x][lab[x]/64]=U(1)<<(lab[x]%64);continue;}
 U nz=0;for(int j=0;j<words;j++)nz|=S[x][j]=S[v.a][j]&S[v.b][j];
 if(!nz)for(int j=0;j<words;j++) S[x][j]=S[v.a][j]|S[v.b][j];}
 Plan p;auto visit=[&](auto&&self,int x,int par)->void{
 int state=par;if(!(S[x][par/64]&(U(1)<<(par%64)))){int bd=100;bool done=false;
 for(int j=0;j<words&&!done;j++)for(U w=S[x][j];w;w&=w-1){int k=64*j+countr_zero(w),d=popcount(unsigned(k^par));if(d<bd){bd=d;state=k;}if(!nearest||d==1){done=true;break;}}}
 if(state!=par)p.push_back({x,state&~par,par&~state});auto&v=t.t[x];if(v.bit>=0){self(self,v.a,state);self(self,v.b,state);}};
 visit(visit,0,0);return p;}
Plan fastSeparate(const Tree&t,const vector<int>&lab,int b){map<int,pair<int,int>>m;
 for(int j=0;j<b;j++){vector<int>l=lab;for(auto &v:l)v=(v>>j)&1;for(auto e:fitch(t,l,1,true)){m[e.x].first|=e.plus<<j;m[e.x].second|=e.minus<<j;}}
 Plan p;for(auto [x,e]:m)p.push_back({x,e.first,e.second});return p;}
struct Front{
 struct V{int bit=-1,a=-1,b=-1,phys=0;};vector<V> t;vector<int> lab;
 int visit(const Tree&tr,int x,const vector<Q>&q){int s=0;bool fixed=true;auto&v=tr.t[x];
 for(int j=0;j<int(q.size());j++){auto one=q[j].one,zero=q[j].zero;
 if((one&~v.any)||(zero&v.all))continue;
 if(!(one&~v.all)&&!(zero&v.any))s|=1<<j;else{fixed=false;break;}}
 int i=int(t.size());t.push_back({-1,-1,-1,x});lab.push_back(s);
 if(!fixed){if(v.bit<0)throw runtime_error("unresolved leaf");int a=visit(tr,v.a,q),b=visit(tr,v.b,q);t[i].bit=v.bit;t[i].a=a;t[i].b=b;}return i;}
};
Plan frontier(const Tree&tr,const vector<Q>&q,bool scalar){
 if(scalar){map<int,pair<int,int>> m;for(int j=0;j<int(q.size());j++)for(auto e:frontier(tr,{q[j]},false)){m[e.x].first|=e.plus<<j;m[e.x].second|=e.minus<<j;}
 Plan p;for(auto [x,pm]:m)p.push_back({x,pm.first,pm.second});return p;}
 Front f;f.visit(tr,0,q);Plan p=fitch(f,f.lab,int(q.size()),true);for(auto &z:p)z.x=f.t[z.x].phys;return p;}
pair<int,int> cost(const Plan&p){int r=0,u=0;for(auto z:p)if(z.x){r++;u+=popcount(unsigned(z.plus|z.minus));}return {r,u};}
using Ans=array<int64_t,8>;
Ans run(const Tree&t,const Plan&p,Range z){Ans out{};for(auto term:p){int64_t val=term.x?t.t[term.x].count(z):z.r-z.l;
 for(unsigned m=term.plus;m;m&=m-1)out[countr_zero(m)]+=val;for(unsigned m=term.minus;m;m&=m-1)out[countr_zero(m)]-=val;}return out;}
vector<Q> readq(string path){ifstream in(path);vector<Q> q;string id;U a,b;I l,r;while(in>>id>>a>>b>>l>>r){if(q.empty()||q.back().id!=id)q.push_back({id,a,b,{}});q.back().ranges.push_back({l,r});}return q;}

struct Columns {
 vector<vector<U>> w; vector<vector<I>> pref; size_t nw;I n;
 Columns(const vector<U>&r):w(64),pref(64),nw((r.size()+63)/64),n(I(r.size())){
 U mix=0;for(U x:r)mix|=x;for(int b=0;b<64;b++)if((mix>>b)&1)w[b].assign(nw,0);
 for(I i=0;i<n;i++)for(U m=r[i];m;m&=m-1)w[countr_zero(m)][i/64]|=U(1)<<(i%64); for(int j=0;j<64;j++)if(!w[j].empty()){pref[j].resize(nw+1);for(size_t k=0;k<nw;k++)pref[j][k+1]=pref[j][k]+popcount(w[j][k]);}
 }
 I rankcol(int j,I x)const{return w[j].empty()?0:pref[j][x/64]+(x%64?popcount(w[j][x/64]&((U(1)<<(x%64))-1)):0);}
 Node cache(const Q&q){Node out;out.w.assign(nw,~U(0));if(n%64)out.w.back()=(U(1)<<(n%64))-1;
 for(U m=q.one|q.zero;m;m&=m-1){int j=countr_zero(m);bool pos=(q.one>>j)&1;if(w[j].empty()){if(pos)fill(out.w.begin(),out.w.end(),0);continue;}
 for(size_t k=0;k<nw;k++)out.w[k]&=pos?w[j][k]:~w[j][k];}
 if(q.one&q.zero)fill(out.w.begin(),out.w.end(),0);out.pref.assign(nw+1,0);for(size_t k=0;k<nw;k++)out.pref[k+1]=out.pref[k]+popcount(out.w[k]);return out;}
};
Plan leafUnion(const Tree&t,const vector<Q>&q){vector<int>lab=leaflabels(t,q);int masks=0,L=0;
 int c[8]{};for(size_t x=0;x<t.t.size();x++)if(t.t[x].bit<0){L++;for(int j=0;j<int(q.size());j++)c[j]+=(lab[x]>>j)&1;}
 for(int j=0;j<int(q.size());j++)if(c[j]*2>L)masks|=1<<j;
 Plan p;if(masks)p.push_back({0,masks,0});if(t.t.size()>1){for(int x=1;x<int(t.t.size());x++)if(t.t[x].bit<0&&lab[x]!=masks)p.push_back({x,lab[x]&~masks,masks&~lab[x]});}
 return p;}
int partition(const Tree&t,const Plan&p,const vector<Q>&q,int H,bool fullonly,int price=1){
 int b=int(q.size()),K=1<<b;vector<int64_t>sub(K);long long add[8]{},cache[8]{};
 for(auto e:p)if(e.x){auto &v=t.t[e.x];int m=e.plus|e.minus;sub[m]+=H*(v.w.empty()?2+2*int(bit_width(v.p.size())):5);
 for(int j=0;j<b;j++)if((m>>j)&1)add[j]+=H;}
 map<pair<U,U>,int> groups;for(int j=0;j<b;j++)groups[{q[j].one,q[j].zero}]|=1<<j;
 vector<int64_t>prep(K);for(auto [key,m]:groups){int ar=popcount(key.first|key.second);if(ar>1&&!(key.first&key.second))prep[m]+=((int64_t(t.n)+63)/64)*(ar+3)*price;}
 for(int j=0;j<b;j++){cache[j]=5LL*H;for(int m=0;m<K;m++)if(m&(1<<j)){sub[m]+=sub[m^(1<<j)];prep[m]+=prep[m^(1<<j)];}}
 long long best=INT64_MAX;int id=0;
 for(int m=0;m<K;m++){if(fullonly&&m&&m!=K-1)continue;long long z=sub[K-1]-sub[(K-1)^m]+prep[K-1]-prep[m];for(int j=0;j<b;j++)z+=(m>>j&1)?add[j]:cache[j];if(z<best){best=z;id=m;}}
 return id;}
int main(int argc,char**argv){try{
 if(argc<3)return 2;string pre=argv[1];ifstream fin(pre+".rows",ios::binary|ios::ate);auto len=fin.tellg();if(len<=0||U(len)%8||U(len)/8>=UINT32_MAX)throw runtime_error("invalid rows");vector<U>row(size_t(len)/8);fin.seekg(0);fin.read((char*)row.data(),len);
 auto t0=Clock::now();Tree tree(row);auto build=elapsed(t0);auto ct=Clock::now();Columns cols(row);auto colbuild=elapsed(ct);size_t tbytes=tree.t.capacity()*sizeof(Node),cbytes=0;for(auto &v:tree.t)tbytes+=4*v.p.capacity()+4*v.pref.capacity()+8*v.w.capacity();for(int j=0;j<64;j++)cbytes+=8*cols.w[j].capacity()+4*cols.pref[j].capacity();validatePrices(tree,8,16,1);auto all=readq(pre+".queries");if(all.empty()||all.size()%8)throw runtime_error("expect bundles of 8");
 ofstream out(argv[2]);out<<"bundle\twidth\tmethod\trep\tranges\tranks\tupdates\tcompile_ns\texec_ns\tdigest\tindex_ns\tnodes\tkeep\tindex_bytes\n";
 for(size_t g=0;g<all.size();g+=8)for(int b:{2,4,8}){
 vector<Q>q(all.begin()+g,all.begin()+g+b);for(auto&v:q)if(v.ranges!=q[0].ranges)throw runtime_error("ranges differ");
 vector<Range> ranges=q[0].ranges;vector<Ans> oracle(ranges.size());

 vector<I> points;for(auto z:ranges){points.push_back(z.l);points.push_back(z.r);}
 sort(points.begin(),points.end());points.erase(unique(points.begin(),points.end()),points.end());
 map<I,Ans> snapshots;Ans cumulative{};I cursor=0;for(I stop:points){if(stop>row.size())throw runtime_error("bad endpoint");for(;cursor<stop;cursor++)for(int j=0;j<b;j++)cumulative[j]+=((row[cursor]&q[j].one)==q[j].one&&!(row[cursor]&q[j].zero));snapshots[stop]=cumulative;}
 for(size_t k=0;k<ranges.size();k++)for(int j=0;j<b;j++)oracle[k][j]=snapshots[ranges[k].r][j]-snapshots[ranges[k].l][j];
 for(int rep=0;rep<3;rep++)for(int a=0;a<13;a++){int method=(a+rep+int(g/8))%13;int A=method==1?4:method==2?16:1;int c=method>=3?0:1;
 auto start=Clock::now();vector<Node> cached;vector<int> which(b,-999);map<pair<U,U>,int> ids;Plan p;int keep=(1<<b)-1;
 if(method==7)keep=0;else if(method==10)p=leafUnion(tree,q);else if(method>=11){p=frontier(tree,q,false);keep=partition(tree,p,q,int(ranges.size()),method==12);
 for(auto&e:p){e.plus&=keep;e.minus&=keep;}p.erase(remove_if(p.begin(),p.end(),[](auto e){return !(e.plus|e.minus);}),p.end());}
 else if(method>=8)p=frontier(tree,q,method==9);else{auto lab=leaflabels(tree,q);p=method==6?fastSeparate(tree,lab,b):method>=4?fitch(tree,lab,b,method==5):method?solveValidatedPrices(tree,lab,b,A,c):separate(tree,lab,b);}
 for(int j=0;j<b;j++)if(!(keep>>j&1)){auto&v=q[j];U mask=v.one|v.zero;
 if((v.one&v.zero)||!mask||has_single_bit(mask)){which[j]=-2;continue;}
 auto [it,added]=ids.emplace(make_pair(v.one,v.zero),int(cached.size()));if(added)cached.push_back(cols.cache(v));which[j]=it->second;}
 auto compile=elapsed(start);
 if(rep==0&&g==0&&b<=4&&method&&method<4){auto ref=cost(solveValidatedPrices(tree,leaflabels(tree,q),b,A,c,true)),opt=cost(p);if(ref.first*A+ref.second*c!=opt.first*A+opt.second*c)throw runtime_error("quadratic objective mismatch");}
 auto [r,u]=cost(p);vector<Ans> actual(ranges.size());start=Clock::now();for(size_t k=0;k<ranges.size();k++){auto z=ranges[k];actual[k]=run(tree,p,z);if(keep!=(1<<b)-1){int64_t counts[8];for(int j=0;j<int(cached.size());j++)counts[j]=cached[j].count(z);for(int j=0;j<b;j++)if(which[j]!=-999){if(which[j]>=0){actual[k][j]=counts[which[j]];continue;}auto&v=q[j];U mask=v.one|v.zero;if(v.one&v.zero)actual[k][j]=0;else if(!mask)actual[k][j]=z.r-z.l;else{int col=countr_zero(mask);I hits=cols.rankcol(col,z.r)-cols.rankcol(col,z.l);actual[k][j]=v.one?hits:z.r-z.l-hits;}}}}
 auto tm=elapsed(start);if(actual!=oracle)throw runtime_error("oracle mismatch");U digest=0;for(auto arr:actual)for(int j=0;j<b;j++)digest=digest*131+U(arr[j]);
 out<<q[0].id<<'\t'<<b<<'\t'<<(method==0?"independent_union":method==1?"joint4":method==2?"joint16":method==3?"joint_rank":method==4?"fitch_first":method==5?"fitch_near":method==6?"scalar_fitch_union":method==7?"cached_bitmaps":method==8?"frontier_joint":method==9?"frontier_scalar":method==10?"leaf_union":method==11?"portfolio":"all_or_none")<<'\t'<<rep<<'\t'<<ranges.size()<<'\t'<<r<<'\t'<<u<<'\t'<<compile<<'\t'<<tm<<'\t'<<digest<<'\t'<<(method==7?colbuild:method>=11?build+colbuild:build)<<'\t'<<tree.t.size()<<'\t'<<keep<<'\t'<<(method==7?cbytes:method>=11?cbytes+tbytes:tbytes)<<'\n';
 }}
 }catch(const exception&e){cerr<<e.what()<<'\n';return 1;} return 0; }
