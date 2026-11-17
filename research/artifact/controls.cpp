
#define main scoped_bundle_entry
#include "bundles.cpp"
#undef main
Plan flatScalar(const Tree&t,const vector<Q>&q){
 vector<int> plus(t.t.size()),minus(t.t.size()),seen;
 for(int j=0;j<int(q.size());j++)for(auto e:frontier(t,{q[j]},false)){
 int x=e.x;if(!plus[x]&&!minus[x])seen.push_back(x);plus[x]|=e.plus<<j;minus[x]|=e.minus<<j;}
 Plan p;
 if(seen.size()*16<t.t.size()){sort(seen.begin(),seen.end());for(int x:seen)p.push_back({x,plus[x],minus[x]});}
 else for(int x=0;x<int(t.t.size());x++)if(plus[x]|minus[x])p.push_back({x,plus[x],minus[x]});
 return p;}
struct Op{int par,col;bool pos;};
struct Words{vector<Op> op{{-1,-1,false}};vector<int>dest;Words(const vector<Q>&q){
 map<tuple<int,int,bool>,int> m;
 for(auto &v:q){if(v.one&v.zero){dest.push_back(-1);continue;}int u=0;
 for(U z=v.one|v.zero;z;z&=z-1){int j=countr_zero(z);bool pos=(v.one>>j)&1;auto key=make_tuple(u,j,pos);auto [it,fresh]=m.emplace(key,int(op.size()));if(fresh)op.push_back({u,j,pos});u=it->second;}dest.push_back(u);}}
 Ans runw(const Columns&c,Range z,vector<U>&w)const{Ans a{};if(z.l==z.r)return a;
 for(size_t i=z.l/64;i<=(z.r-1)/64;i++){w[0]=~U(0);if(i==z.l/64)w[0]&=~U(0)<<(z.l%64);if(i==(z.r-1)/64&&z.r%64)w[0]&=(U(1)<<(z.r%64))-1;
 for(size_t j=1;j<op.size();j++){auto a=op[j];U bits=c.w[a.col].empty()?0:c.w[a.col][i];w[j]=w[a.par]&(a.pos?bits:~bits);}
 for(int j=0;j<int(dest.size());j++)if(dest[j]>=0)a[j]+=popcount(w[dest[j]]);}
 return a;}
};
int main(int argc,char**argv){try{if(argc<3)return 2;string pre=argv[1];ifstream in(pre+".rows",ios::ate|ios::binary);auto n=in.tellg();if(n<=0)return 2;vector<U>r(size_t(n)/8);in.seekg(0);in.read((char*)r.data(),n);Tree t(r);Columns c(r);auto all=readq(pre+".queries");ofstream out(argv[2]);out<<"bundle\tmethod\trep\tcompile_ns\texec_ns\tranks\tupdates\tdigest\n";
 for(size_t g=0;g<all.size();g+=8){vector<Q>q(all.begin()+g,all.begin()+g+8);auto rr=q[0].ranges;
 auto st=Clock::now();Plan p=flatScalar(t,q);auto joint=frontier(t,q,false);
 vector<Ans>ref;for(auto z:rr)ref.push_back(run(t,joint,z));
 for(int rep=0;rep<3;rep++)for(int a=0;a<3;a++){int m=(a+rep+g/8)%3;Plan pay;
 st=Clock::now();if(m==0)pay=flatScalar(t,q);else if(m==1)pay=frontier(t,q,false);
 Words w(m==2?q:vector<Q>{});vector<U>buf(w.op.size());auto comp=elapsed(st);
 vector<Ans>ans(rr.size());st=Clock::now();for(size_t i=0;i<rr.size();i++)ans[i]=m==2?w.runw(c,rr[i],buf):run(t,pay,rr[i]);auto ex=elapsed(st);
 if(ans!=ref)throw runtime_error("control mismatch");U dg=0;for(auto a:ans)for(auto y:a)dg=dg*131+y;auto [nr,nu]=cost(pay);
 out<<q[0].id<<'\t'<<(m==0?"flat_scalar":m==1?"frontier_joint":"shared_word_scan")<<'\t'<<rep<<'\t'<<comp<<'\t'<<ex<<'\t'<<nr<<'\t'<<nu<<'\t'<<dg<<'\n';}}
 }catch(const exception&e){cerr<<e.what();return 1;} }
